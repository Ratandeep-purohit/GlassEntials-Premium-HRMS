from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from django.db.models import Q

from employees.models import Employee
from payroll.engine.attendance_days import PayrollAttendanceService
from payroll.engine.formula_runner import evaluate_formula
from payroll.engine.statutory import calculate_statutory_deductions
from payroll.models import (
    Arrear,
    EmployeeTaxProfile,
    FinancialYear,
    LoanInstallment,
    SalaryComponent,
    SalaryStructure,
    TaxCalculationSnapshot,
)


ZERO = Decimal("0.00")


@dataclass
class PayrollPreviewRow:
    employee: Employee
    structure: SalaryStructure | None
    day_summary: object
    earnings: Decimal = ZERO
    deductions: Decimal = ZERO
    net_salary: Decimal = ZERO
    salary_components: int = 0
    earning_components: int = 0
    deduction_components: int = 0
    warnings: list[str] = field(default_factory=list)
    can_process: bool = True

    @property
    def status_label(self):
        if not self.can_process:
            return "Blocked"
        if self.warnings:
            return "Review"
        return "Ready"


@dataclass
class PayrollPreview:
    payroll_run: object
    rows: list[PayrollPreviewRow]
    total_gross: Decimal
    total_deductions: Decimal
    total_net: Decimal
    total_employees: int
    eligible_count: int
    blocked_count: int
    warning_count: int


class PayrollPreviewBuilder:
    """
    Builds a payroll dry run for HR review.

    This intentionally does not create payslips, mutate loan installments, post
    arrears, or update the PayrollRun totals. The calculation mirrors the live
    processor so HR can review attendance impact before final processing.
    """

    def __init__(self, payroll_run):
        self.payroll_run = payroll_run
        self.organization = payroll_run.organization
        self.month = int(payroll_run.month)
        self.year = int(payroll_run.year)
        self.period_start = date(self.year, self.month, 1)
        self.period_end = date(
            self.year,
            self.month,
            self._month_last_day(self.year, self.month),
        )

    def build(self):
        employees = self._employees()
        self.active_structures = self._active_structures()
        self.attendance_service = PayrollAttendanceService(self.organization, self.month, self.year)
        self.day_summary_by_employee = self.attendance_service.build()
        self.components_by_code = {
            component.code: component
            for component in SalaryComponent.objects.filter(organization=self.organization)
        }
        self.installments_by_employee = self._loan_installments()
        self.arrears_by_employee = self._arrears()
        self.tax_profiles_by_employee, self.tax_snapshots_by_profile = self._tax_data()

        rows = [self._build_row(employee) for employee in employees]
        processable_rows = [row for row in rows if row.can_process]

        return PayrollPreview(
            payroll_run=self.payroll_run,
            rows=rows,
            total_gross=self._money(sum((row.earnings for row in processable_rows), ZERO)),
            total_deductions=self._money(sum((row.deductions for row in processable_rows), ZERO)),
            total_net=self._money(sum((row.net_salary for row in processable_rows), ZERO)),
            total_employees=len(rows),
            eligible_count=len(processable_rows),
            blocked_count=len([row for row in rows if not row.can_process]),
            warning_count=len([row for row in rows if row.warnings]),
        )

    def _employees(self):
        employees = Employee.objects.filter(
            organization=self.organization,
            is_active=True,
            is_deleted=False,
        ).select_related("department", "designation").order_by("employee_id", "first_name")
        if self.payroll_run.department:
            employees = employees.filter(department=self.payroll_run.department)
        return list(employees)

    def _active_structures(self):
        structures = (
            SalaryStructure.objects.filter(
                organization=self.organization,
                is_active=True,
                effective_date__lte=self.period_end,
            )
            .filter(Q(end_date__isnull=True) | Q(end_date__gte=self.period_start))
            .order_by("employee_id", "-effective_date")
            .prefetch_related("items__component")
        )

        active_structures = {}
        for structure in structures:
            if structure.employee_id not in active_structures:
                active_structures[structure.employee_id] = structure
        return active_structures

    def _loan_installments(self):
        installments = LoanInstallment.objects.filter(
            loan__organization=self.organization,
            due_month=self.month,
            due_year=self.year,
            status=LoanInstallment.InstallmentStatus.PENDING,
        ).select_related("loan")
        by_employee = {}
        for installment in installments:
            by_employee.setdefault(installment.loan.employee_id, []).append(installment)
        return by_employee

    def _arrears(self):
        arrears = Arrear.objects.filter(
            organization=self.organization,
            status=Arrear.ArrearStatus.PENDING,
        ).select_related("component")
        by_employee = {}
        for arrear in arrears:
            by_employee.setdefault(arrear.employee_id, []).append(arrear)
        return by_employee

    def _tax_data(self):
        fy = FinancialYear.objects.filter(name=self._financial_year_name()).first()
        if not fy:
            return {}, {}

        profiles = EmployeeTaxProfile.objects.filter(
            employee__organization=self.organization,
            financial_year=fy,
        ).select_related("selected_regime")
        profiles_by_employee = {profile.employee_id: profile for profile in profiles}

        snapshots_by_profile = {}
        snapshots = TaxCalculationSnapshot.objects.filter(
            tax_profile__in=profiles,
            is_active_for_payroll=True,
        ).order_by("tax_profile_id", "-snapshot_date")
        for snapshot in snapshots:
            if snapshot.tax_profile_id not in snapshots_by_profile:
                snapshots_by_profile[snapshot.tax_profile_id] = snapshot

        return profiles_by_employee, snapshots_by_profile

    def _build_row(self, employee):
        structure = self.active_structures.get(employee.id)
        day_summary = self.day_summary_by_employee.get(
            employee.id,
            self.attendance_service.default_summary(),
        )

        row = PayrollPreviewRow(
            employee=employee,
            structure=structure,
            day_summary=day_summary,
        )

        if not structure:
            row.can_process = False
            row.warnings.append("No active salary structure effective for this payroll period.")
            return row

        if day_summary.working_days > ZERO and day_summary.paid_days <= ZERO:
            row.warnings.append("No paid attendance or paid leave found for this period.")

        context = {
            "basic": structure.basic_salary,
            "gross": structure.gross_salary,
            "ctc": structure.ctc,
            "paid_days": day_summary.paid_days,
            "total_days": day_summary.working_days,
            "calendar_days": Decimal(str(self.period_end.day)),
            "lop_days": day_summary.lop_days,
            "attendance_paid_days": day_summary.attendance_paid_days,
            "paid_leave_days": day_summary.paid_leave_days,
            "lop_leave_days": day_summary.lop_leave_days,
        }

        try:
            self._apply_structure_items(row, structure, context, day_summary)
            self._apply_statutory_deductions(row, structure)
            self._apply_loan_installments(row, employee)
            self._apply_arrears(row, employee)
            self._apply_tds(row, employee)
        except Exception as exc:
            row.can_process = False
            row.warnings.append(str(exc))
            row.earnings = ZERO
            row.deductions = ZERO
            row.net_salary = ZERO
            return row

        row.earnings = self._money(row.earnings)
        row.deductions = self._money(row.deductions)
        row.net_salary = self._money(max(row.earnings - row.deductions, ZERO))

        if row.salary_components == 0:
            row.warnings.append("Salary structure has no components.")
        if row.net_salary <= ZERO and row.earnings > ZERO:
            row.warnings.append("Deductions are equal to or higher than earnings.")

        return row

    def _apply_structure_items(self, row, structure, context, day_summary):
        for item in structure.items.all():
            component = item.component
            value = self._structure_item_value(item, structure, context)

            if component.is_calculated_on_attendance and day_summary.working_days > ZERO:
                value = value * day_summary.paid_days / day_summary.working_days

            amount = self._money(value)
            row.salary_components += 1
            if component.component_type == SalaryComponent.ComponentType.EARNING:
                row.earnings += amount
                row.earning_components += 1
            else:
                row.deductions += amount
                row.deduction_components += 1

    def _structure_item_value(self, item, structure, context):
        component = item.component
        if component.calculation_type == SalaryComponent.CalculationType.FIXED:
            return item.fixed_amount
        if component.calculation_type == SalaryComponent.CalculationType.PERCENTAGE:
            return structure.basic_salary * item.percentage
        if component.calculation_type == SalaryComponent.CalculationType.FORMULA:
            return evaluate_formula(item.formula_override or component.formula, context)
        return ZERO

    def _apply_statutory_deductions(self, row, structure):
        for code, amount in calculate_statutory_deductions(
            structure.basic_salary,
            structure.gross_salary,
        ).items():
            if amount > ZERO and self.components_by_code.get(code):
                row.deductions += self._money(amount)
                row.deduction_components += 1

    def _apply_loan_installments(self, row, employee):
        for installment in self.installments_by_employee.get(employee.id, []):
            row.deductions += self._money(installment.emi_amount)
            row.deduction_components += 1

    def _apply_arrears(self, row, employee):
        for arrear in self.arrears_by_employee.get(employee.id, []):
            amount = self._money(arrear.amount)
            if arrear.arrear_type == Arrear.ArrearType.EARNING:
                row.earnings += amount
                row.earning_components += 1
            else:
                row.deductions += amount
                row.deduction_components += 1

    def _apply_tds(self, row, employee):
        tax_profile = self.tax_profiles_by_employee.get(employee.id)
        snapshot = self.tax_snapshots_by_profile.get(tax_profile.id) if tax_profile else None
        if snapshot and snapshot.monthly_tds > ZERO:
            row.deductions += self._money(snapshot.monthly_tds)
            row.deduction_components += 1

    def _financial_year_name(self):
        if self.month >= 4:
            return f"{self.year}-{self.year + 1}"
        return f"{self.year - 1}-{self.year}"

    @staticmethod
    def _month_last_day(year, month):
        import calendar

        return calendar.monthrange(year, month)[1]

    @staticmethod
    def _money(value):
        return Decimal(value or ZERO).quantize(Decimal("0.01"))
