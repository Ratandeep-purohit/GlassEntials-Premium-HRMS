import calendar
from datetime import date
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from .formula_runner import evaluate_formula
from .statutory import calculate_statutory_deductions
from .attendance_days import PayrollAttendanceService
from ..models import (
    PayrollRun, EmployeePayslip, PayslipItem, 
    SalaryStructure, SalaryStructureItem, SalaryComponent,
    LoanInstallment, Arrear, PayrollTDSSyncLog
)

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

        self._clear_editable_run_outputs()

        # Identify employees to process (filter by department if applicable)
        from employees.models import Employee
        employees = Employee.objects.filter(
            organization=self.payroll_run.organization,
            is_active=True
        )
        if self.payroll_run.department:
            employees = employees.filter(department=self.payroll_run.department)

        # PREFETCH DATA #
        org = self.payroll_run.organization
        period_start = date(self.year, self.month, 1)
        period_end = date(self.year, self.month, self.total_days)
        
        # 1. Salary Structures
        structures = SalaryStructure.objects.filter(
            organization=org,
            is_active=True,
            effective_date__lte=period_end
        ).filter(
            Q(end_date__isnull=True) | Q(end_date__gte=period_start)
        ).order_by('employee_id', '-effective_date').prefetch_related('items__component')
        self.active_structures = {}
        for s in structures:
            if s.employee_id not in self.active_structures:
                self.active_structures[s.employee_id] = s
                
        # 2. Attendance, leave and payroll-impact days
        self.attendance_service = PayrollAttendanceService(org, self.month, self.year)
        self.day_summary_by_employee = self.attendance_service.build()
        
        # 3. Global Salary Components
        self.components_by_code = {
            c.code: c for c in SalaryComponent.objects.filter(organization=org)
        }
        
        # 4. Loan Installments
        installments = LoanInstallment.objects.filter(
            loan__organization=org,
            due_month=self.month,
            due_year=self.year,
            status=LoanInstallment.InstallmentStatus.PENDING
        ).select_related('loan')
        self.installments_by_employee = {}
        for inst in installments:
            self.installments_by_employee.setdefault(inst.loan.employee_id, []).append(inst)
            
        # 5. Arrears
        arrears = Arrear.objects.filter(
            organization=org,
            status=Arrear.ArrearStatus.PENDING
        ).select_related('component')
        self.arrears_by_employee = {}
        for arr in arrears:
            self.arrears_by_employee.setdefault(arr.employee_id, []).append(arr)
            
        # 6. Taxes & TDS
        fy_name = self._get_financial_year()
        from ..models import FinancialYear, EmployeeTaxProfile, TaxCalculationSnapshot
        self.fy = FinancialYear.objects.filter(name=fy_name).first()
        self.tax_profiles_by_employee = {}
        self.tax_snapshots_by_profile = {}
        
        if self.fy:
            tps = EmployeeTaxProfile.objects.filter(
                employee__organization=org,
                financial_year=self.fy
            ).select_related('selected_regime')
            self.tax_profiles_by_employee = {tp.employee_id: tp for tp in tps}
            
            snaps = TaxCalculationSnapshot.objects.filter(
                tax_profile__in=tps,
                is_active_for_payroll=True
            ).order_by('tax_profile_id', '-snapshot_date')
            for snap in snaps:
                if snap.tax_profile_id not in self.tax_snapshots_by_profile:
                    self.tax_snapshots_by_profile[snap.tax_profile_id] = snap

        # Bulk accumulation lists
        self.payslip_items_to_create = []
        self.installments_to_update = []
        self.arrears_to_update = []
        self.tds_logs_to_create = []

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
                
        # Execute Bulk DB Operations
        if self.payslip_items_to_create:
            PayslipItem.objects.bulk_create(self.payslip_items_to_create)
        if self.installments_to_update:
            LoanInstallment.objects.bulk_update(self.installments_to_update, ['status', 'payslip'])
        if self.arrears_to_update:
            Arrear.objects.bulk_update(self.arrears_to_update, ['status', 'processed_in_payroll', 'processed_payslip'])
        if self.tds_logs_to_create:
            PayrollTDSSyncLog.objects.bulk_create(self.tds_logs_to_create)

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
        structure = self.active_structures.get(employee.id)

        if not structure:
            return None

        # 2. Calculate attendance, leave and LOP impact
        day_summary = self._get_day_summary(employee)
        working_days = int(day_summary.working_days)
        paid_days = day_summary.paid_days
        lop_days = day_summary.lop_days

        # 3. Initialize Payslip
        payslip = EmployeePayslip.objects.create(
            organization=self.payroll_run.organization,
            payroll_run=self.payroll_run,
            employee=employee,
            total_working_days=working_days,
            paid_days=paid_days,
            lop_days=lop_days,
            status=EmployeePayslip.Status.DRAFT,
            remarks=day_summary.remarks,
        )

        # 4. Process Earnings & Deductions from Structure
        context = {
            'basic': structure.basic_salary,
            'gross': structure.gross_salary,
            'ctc': structure.ctc,
            'paid_days': paid_days,
            'total_days': day_summary.working_days,
            'calendar_days': Decimal(str(self.total_days)),
            'lop_days': lop_days,
            'attendance_paid_days': day_summary.attendance_paid_days,
            'paid_leave_days': day_summary.paid_leave_days,
            'lop_leave_days': day_summary.lop_leave_days,
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
            if comp.is_calculated_on_attendance and day_summary.working_days > 0:
                value = (value * paid_days / day_summary.working_days)

            # Save PayslipItem
            amount = value.quantize(Decimal("0.01"))
            self.payslip_items_to_create.append(
                PayslipItem(
                    organization=self.payroll_run.organization,
                    payslip=payslip,
                    component=comp,
                    item_type=comp.component_type,
                    amount=amount
                )
            )

            if comp.component_type == SalaryComponent.ComponentType.EARNING:
                gross_earnings += amount
            else:
                total_deductions += amount

        # 5. Statutory Deductions
        stat_deductions = calculate_statutory_deductions(
            structure.basic_salary, 
            structure.gross_salary
        )
        for code, amount in stat_deductions.items():
            if amount > 0:
                comp = self.components_by_code.get(code)
                if comp:
                    self.payslip_items_to_create.append(
                        PayslipItem(
                            organization=self.payroll_run.organization,
                            payslip=payslip,
                            component=comp,
                            item_type=PayslipItem.ItemType.DEDUCTION,
                            amount=amount
                        )
                    )
                    total_deductions += amount

        # 6. Loans (EMI Recovery)
        installments = self.installments_by_employee.get(employee.id, [])
        for inst in installments:
            comp = self.components_by_code.get("LOAN_RECOVERY")
            if not comp:
                # Create a default loan recovery component if missing
                comp = SalaryComponent.objects.create(
                    organization=self.payroll_run.organization,
                    code="LOAN_RECOVERY",
                    name="Loan EMI Recovery",
                    component_type=SalaryComponent.ComponentType.DEDUCTION,
                    calculation_type=SalaryComponent.CalculationType.FIXED
                )
                self.components_by_code["LOAN_RECOVERY"] = comp
            
            self.payslip_items_to_create.append(
                PayslipItem(
                    organization=self.payroll_run.organization,
                    payslip=payslip,
                    component=comp,
                    item_type=PayslipItem.ItemType.DEDUCTION,
                    amount=inst.emi_amount,
                    calculation_note=f"Loan {inst.loan.loan_number} EMI #{inst.installment_number}"
                )
            )
            total_deductions += inst.emi_amount
            # Mark installment as deducted (link to payslip)
            inst.status = LoanInstallment.InstallmentStatus.DEDUCTED
            inst.payslip = payslip
            self.installments_to_update.append(inst)

        # 7. Arrears
        arrears = self.arrears_by_employee.get(employee.id, [])
        for arr in arrears:
            self.payslip_items_to_create.append(
                PayslipItem(
                    organization=self.payroll_run.organization,
                    payslip=payslip,
                    component=arr.component,
                    item_type=arr.arrear_type,
                    amount=arr.amount,
                    calculation_note=f"Arrear for {arr.from_month}/{arr.from_year}"
                )
            )
            if arr.arrear_type == Arrear.ArrearType.EARNING:
                gross_earnings += arr.amount
            else:
                total_deductions += arr.amount
            
            # Mark arrear as processed
            arr.status = Arrear.ArrearStatus.PROCESSED
            arr.processed_in_payroll = self.payroll_run
            arr.processed_payslip = payslip
            self.arrears_to_update.append(arr)

        # 8. Income Tax (TDS)
        tax_profile = self.tax_profiles_by_employee.get(employee.id)
        snapshot = self.tax_snapshots_by_profile.get(tax_profile.id) if tax_profile else None
            
        if snapshot and snapshot.monthly_tds > Decimal("0.00"):
            comp = self.components_by_code.get("TDS")
            if not comp:
                comp = SalaryComponent.objects.create(
                    organization=self.payroll_run.organization,
                    code="TDS",
                    name="Income Tax (TDS)",
                    component_type=SalaryComponent.ComponentType.DEDUCTION,
                    calculation_type=SalaryComponent.CalculationType.FIXED
                )
                self.components_by_code["TDS"] = comp
            
            tds_amount = snapshot.monthly_tds.quantize(Decimal("0.01"))
            self.payslip_items_to_create.append(
                PayslipItem(
                    organization=self.payroll_run.organization,
                    payslip=payslip,
                    component=comp,
                    item_type=PayslipItem.ItemType.DEDUCTION,
                    amount=tds_amount,
                    calculation_note=f"TDS based on {tax_profile.selected_regime.regime_type if tax_profile.selected_regime else 'NEW'} Regime"
                )
            )
            total_deductions += tds_amount
            
            self.tds_logs_to_create.append(
                PayrollTDSSyncLog(
                    organization=self.payroll_run.organization,
                    tax_profile=tax_profile,
                    payroll_run=self.payroll_run,
                    synced_tds_amount=tds_amount
                )
            )

        # Finalize Payslip totals
        payslip.gross_earnings = gross_earnings.quantize(Decimal("0.01"))
        payslip.total_deductions = total_deductions.quantize(Decimal("0.01"))
        
        # Clamp net salary to 0 to prevent negative payouts
        net = gross_earnings - total_deductions
        payslip.net_salary = max(net, Decimal("0.00")).quantize(Decimal("0.01"))
        
        payslip.status = EmployeePayslip.Status.GENERATED
        payslip.save()
        self._post_leave_payroll_impacts(employee)

        return payslip

    def _clear_editable_run_outputs(self):
        """Clear generated artifacts so reruns pick up changed salary components."""
        locked_exists = self.payroll_run.payslips.filter(
            status__in=[
                EmployeePayslip.Status.FINALIZED,
                EmployeePayslip.Status.PAID,
            ]
        ).exists()
        if locked_exists:
            raise ValueError("Cannot rerun payroll because one or more payslips are finalized or paid.")

        editable_payslips = self.payroll_run.payslips.exclude(
            status__in=[
                EmployeePayslip.Status.FINALIZED,
                EmployeePayslip.Status.PAID,
            ]
        )
        editable_payslip_ids = list(editable_payslips.values_list('id', flat=True))
        if not editable_payslip_ids:
            PayrollTDSSyncLog.objects.filter(payroll_run=self.payroll_run).delete()
            return

        LoanInstallment.objects.filter(
            payslip_id__in=editable_payslip_ids,
            status=LoanInstallment.InstallmentStatus.DEDUCTED,
        ).update(
            status=LoanInstallment.InstallmentStatus.PENDING,
            payslip=None,
        )

        Arrear.objects.filter(
            Q(processed_payslip_id__in=editable_payslip_ids)
            | Q(processed_in_payroll=self.payroll_run)
        ).update(
            status=Arrear.ArrearStatus.PENDING,
            processed_in_payroll=None,
            processed_payslip=None,
        )

        PayrollTDSSyncLog.objects.filter(payroll_run=self.payroll_run).delete()
        editable_payslips.delete()

    def _get_day_summary(self, employee):
        """Return payroll-ready attendance/leave days for an employee."""
        return self.day_summary_by_employee.get(employee.id, self.attendance_service.default_summary())

    def _post_leave_payroll_impacts(self, employee):
        """Link consumed leave impacts to the payroll run for traceability."""
        from leaves.models import LeavePayrollImpact

        LeavePayrollImpact.objects.filter(
            employee=employee,
            month=self.month,
            year=self.year,
            status__in=["PENDING", "ADJUSTED"],
        ).update(
            payroll_run=self.payroll_run,
            status="POSTED",
        )

    def _get_financial_year(self):
        """Returns string like '2024-2025' based on payroll month and year."""
        if self.month >= 4:
            return f"{self.year}-{self.year + 1}"
        else:
            return f"{self.year - 1}-{self.year}"
