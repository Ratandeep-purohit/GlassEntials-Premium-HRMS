import calendar
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .formula_runner import evaluate_formula
from .statutory import calculate_statutory_deductions
from ..models import (
    PayrollRun, EmployeePayslip, PayslipItem, 
    SalaryStructure, SalaryStructureItem, SalaryComponent,
    LoanInstallment, Arrear
)
from attendance.models import Attendance
from leaves.models import LeaveRequest

class PayrollProcessor:
    """
    The main engine to process monthly payroll batches.
    """

    def __init__(self, payroll_run_id):
        self.payroll_run = PayrollRun.objects.get(pk=payroll_run_id)
        self.month = self.payroll_run.month
        self.year = self.payroll_run.year
        self.total_days = calendar.monthrange(self.year, self.month)[1]

    @transaction.atomic
    def process(self):
        """Execute the payroll run for all relevant employees."""
        self.payroll_run.status = PayrollRun.Status.PROCESSING
        self.payroll_run.save()

        # Clear existing draft payslips for this run to allow re-runs
        self.payroll_run.payslips.filter(status=EmployeePayslip.Status.DRAFT).delete()

        # Identify employees to process (filter by department if applicable)
        from employees.models import Employee
        employees = Employee.objects.filter(is_active=True)
        if self.payroll_run.department:
            employees = employees.filter(department=self.payroll_run.department)

        total_gross = Decimal("0.00")
        total_deductions = Decimal("0.00")
        total_net = Decimal("0.00")
        processed_count = 0

        for employee in employees:
            payslip = self._process_employee(employee)
            if payslip:
                total_gross += payslip.gross_earnings
                total_deductions += payslip.total_deductions
                total_net += payslip.net_salary
                processed_count += 1

        # Update PayrollRun totals
        self.payroll_run.total_employees = processed_count
        self.payroll_run.total_gross = total_gross
        self.payroll_run.total_deductions = total_deductions
        self.payroll_run.total_net = total_net
        self.payroll_run.status = PayrollRun.Status.DRAFT  # Set back to draft for review
        self.payroll_run.save()

        return processed_count

    def _process_employee(self, employee):
        """Calculate and save payslip for a single employee."""
        
        # 1. Get Active Salary Structure
        structure = SalaryStructure.objects.filter(
            employee=employee,
            is_active=True,
            effective_date__lte=timezone.now().date()
        ).order_by("-effective_date").first()

        if not structure:
            return None

        # 2. Calculate Attendance / LOP
        # Simplified: Count days with status.is_paid=False in Attendance
        # And LeaveRequest where status='APPROVED' and leave_type.is_paid=False
        lop_days = self._get_lop_days(employee)
        paid_days = Decimal(str(self.total_days)) - lop_days

        # 3. Initialize Payslip
        payslip = EmployeePayslip.objects.create(
            payroll_run=self.payroll_run,
            employee=employee,
            total_working_days=self.total_days,
            paid_days=paid_days,
            lop_days=lop_days,
            status=EmployeePayslip.Status.DRAFT
        )

        # 4. Process Earnings & Deductions from Structure
        context = {
            'basic': structure.basic_salary,
            'gross': structure.gross_salary,
            'ctc': structure.ctc,
            'paid_days': paid_days,
            'total_days': Decimal(str(self.total_days))
        }

        gross_earnings = Decimal("0.00")
        total_deductions = Decimal("0.00")

        for item in structure.items.all():
            comp = item.component
            
            # Base value calculation
            if comp.calculation_type == SalaryComponent.CalculationType.FIXED:
                value = item.fixed_amount
            elif comp.calculation_type == SalaryComponent.CalculationType.PERCENTAGE:
                value = (structure.basic_salary * item.percentage)
            elif comp.calculation_type == SalaryComponent.CalculationType.FORMULA:
                formula = item.formula_override or comp.formula
                value = evaluate_formula(formula, context)
            else:
                value = Decimal("0.00")

            # Apply LOP if applicable
            if comp.is_calculated_on_attendance and self.total_days > 0:
                value = (value * paid_days / Decimal(str(self.total_days)))

            # Save PayslipItem
            PayslipItem.objects.create(
                payslip=payslip,
                component=comp,
                item_type=comp.component_type,
                amount=value.quantize(Decimal("0.01"))
            )

            if comp.component_type == SalaryComponent.ComponentType.EARNING:
                gross_earnings += value
            else:
                total_deductions += value

        # 5. Statutory Deductions
        stat_deductions = calculate_statutory_deductions(
            structure.basic_salary, 
            structure.gross_salary
        )
        for code, amount in stat_deductions.items():
            if amount > 0:
                comp = SalaryComponent.objects.filter(code=code).first()
                if comp:
                    PayslipItem.objects.create(
                        payslip=payslip,
                        component=comp,
                        item_type=PayslipItem.ItemType.DEDUCTION,
                        amount=amount
                    )
                    total_deductions += amount

        # 6. Loans (EMI Recovery)
        installments = LoanInstallment.objects.filter(
            loan__employee=employee,
            due_month=self.month,
            due_year=self.year,
            status=LoanInstallment.InstallmentStatus.PENDING
        )
        for inst in installments:
            comp = SalaryComponent.objects.filter(code="LOAN_RECOVERY").first()
            if not comp:
                # Create a default loan recovery component if missing
                comp = SalaryComponent.objects.get_or_create(
                    code="LOAN_RECOVERY",
                    name="Loan EMI Recovery",
                    component_type=SalaryComponent.ComponentType.DEDUCTION,
                    calculation_type=SalaryComponent.CalculationType.FIXED
                )[0]
            
            PayslipItem.objects.create(
                payslip=payslip,
                component=comp,
                item_type=PayslipItem.ItemType.DEDUCTION,
                amount=inst.emi_amount,
                calculation_note=f"Loan {inst.loan.loan_number} EMI #{inst.installment_number}"
            )
            total_deductions += inst.emi_amount
            # Mark installment as deducted (link to payslip)
            inst.status = LoanInstallment.InstallmentStatus.DEDUCTED
            inst.payslip = payslip
            inst.save()

        # 7. Arrears
        arrears = Arrear.objects.filter(
            employee=employee,
            status=Arrear.ArrearStatus.PENDING
        )
        for arr in arrears:
            PayslipItem.objects.create(
                payslip=payslip,
                component=arr.component,
                item_type=arr.arrear_type,
                amount=arr.amount,
                calculation_note=f"Arrear for {arr.from_month}/{arr.from_year}"
            )
            if arr.arrear_type == Arrear.ArrearType.EARNING:
                gross_earnings += arr.amount
            else:
                total_deductions += arr.amount
            
            # Mark arrear as processed
            arr.status = Arrear.ArrearStatus.PROCESSED
            arr.processed_in_payroll = self.payroll_run
            arr.processed_payslip = payslip
            arr.save()

        # 8. Income Tax (TDS)
        from ..models import EmployeeTaxProfile, TaxCalculationSnapshot, PayrollTDSSyncLog, FinancialYear
        fy_name = self._get_financial_year()
        fy = FinancialYear.objects.filter(name=fy_name).first()
        
        tax_profile = None
        if fy:
            tax_profile = EmployeeTaxProfile.objects.filter(
                employee=employee,
                financial_year=fy
            ).first()
            
        snapshot = None
        if tax_profile:
            snapshot = TaxCalculationSnapshot.objects.filter(
                tax_profile=tax_profile,
                is_active_for_payroll=True
            ).order_by('-snapshot_date').first()
            
        if snapshot and snapshot.monthly_tds > Decimal("0.00"):
            comp = SalaryComponent.objects.filter(code="TDS").first()
            if not comp:
                comp = SalaryComponent.objects.get_or_create(
                    code="TDS",
                    name="Income Tax (TDS)",
                    component_type=SalaryComponent.ComponentType.DEDUCTION,
                    calculation_type=SalaryComponent.CalculationType.FIXED
                )[0]
            
            tds_amount = snapshot.monthly_tds.quantize(Decimal("0.01"))
            PayslipItem.objects.create(
                payslip=payslip,
                component=comp,
                item_type=PayslipItem.ItemType.DEDUCTION,
                amount=tds_amount,
                calculation_note=f"TDS based on {tax_profile.selected_regime.regime_type if tax_profile.selected_regime else 'NEW'} Regime"
            )
            total_deductions += tds_amount
            
            # Log TDS Sync
            PayrollTDSSyncLog.objects.create(
                organization=self.payroll_run.organization,
                tax_profile=tax_profile,
                payroll_run=self.payroll_run,
                synced_tds_amount=tds_amount
            )

        # Finalize Payslip totals
        payslip.gross_earnings = gross_earnings.quantize(Decimal("0.01"))
        payslip.total_deductions = total_deductions.quantize(Decimal("0.01"))
        
        # Clamp net salary to 0 to prevent negative payouts
        net = gross_earnings - total_deductions
        payslip.net_salary = max(net, Decimal("0.00")).quantize(Decimal("0.01"))
        
        payslip.status = EmployeePayslip.Status.GENERATED
        payslip.save()

        return payslip

    def _get_lop_days(self, employee):
        """Calculate Loss of Pay days for the month."""
        # This is a simplified implementation. 
        # In production, it would query Attendance and LeaveRequest.
        lop_from_attendance = Attendance.objects.filter(
            employee=employee,
            date__month=self.month,
            date__year=self.year,
            status__is_paid=False
        ).count()
        
        # We can expand this with leave logic
        return Decimal(str(lop_from_attendance))

    def _get_financial_year(self):
        """Returns string like '2024-2025' based on payroll month and year."""
        if self.month >= 4:
            return f"{self.year}-{self.year + 1}"
        else:
            return f"{self.year - 1}-{self.year}"
