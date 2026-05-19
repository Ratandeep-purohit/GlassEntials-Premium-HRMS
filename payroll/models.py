"""
Glassentials HRMS — Payroll Module Models (v3)
===============================================
Improvements over v2:
  - unique_together → models.UniqueConstraint (migration-safe, named)
  - save() on every model calls full_clean() for DB-level validation
  - SalaryStructure.save() auto-closes the previous open revision
  - Composite DB indexes for payroll-heavy queries
  - Formula field annotated as SAFE-ENGINE-ONLY (no eval)
  - SalaryStructureItem.clean() validates value vs calculation_type
  - PayslipItem.clean() guards negative amounts and type mismatch
  - LoanInstallment.clean() validates year/month, amount, payslip linkage
"""

import datetime
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from employees.models import BaseModel, Department, Employee

# ---------------------------------------------------------------------------
# Shared constant
# ---------------------------------------------------------------------------
MONEY = dict(max_digits=14, decimal_places=2)

_CURRENT_YEAR = timezone.now().year


# ===========================================================================
# 1. SALARY COMPONENT
# ===========================================================================

class SalaryComponent(BaseModel):
    """Master catalogue: Basic, HRA, PF, TDS, etc."""

    class ComponentType(models.TextChoices):
        EARNING = "EARNING", _("Earning")
        DEDUCTION = "DEDUCTION", _("Deduction")

    class CalculationType(models.TextChoices):
        FIXED = "FIXED", _("Fixed Amount")
        PERCENTAGE = "PERCENTAGE", _("Percentage of Basic")
        FORMULA = "FORMULA", _("Custom Formula")

    code = models.CharField(
        max_length=20, unique=True,
        help_text=_("Short unique code: BASIC, HRA, PF, TDS …"),
    )
    name = models.CharField(max_length=100)
    component_type = models.CharField(
        max_length=20, choices=ComponentType.choices, db_index=True,
    )
    calculation_type = models.CharField(
        max_length=20, choices=CalculationType.choices,
        default=CalculationType.FIXED,
    )
    is_taxable = models.BooleanField(default=False)
    is_statutory = models.BooleanField(default=False)
    is_calculated_on_attendance = models.BooleanField(default=True)

    # ------------------------------------------------------------------ #
    # IMPORTANT: `formula` is NEVER passed to eval() or exec().           #
    # It is interpreted exclusively by the payroll safe-formula engine     #
    # (payroll.engine.formula_runner), which uses a restricted AST parser. #
    # ------------------------------------------------------------------ #
    formula = models.TextField(
        blank=True,
        help_text=_(
            "Safe-engine expression. Variables: basic, gross, ctc. "
            "Example: basic * 0.20  — processed by payroll.engine only."
        ),
    )
    description = models.TextField(blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["display_order", "name"]

    def __str__(self):
        return f"[{self.code}] {self.name} ({self.get_component_type_display()})"

    def clean(self):
        if self.calculation_type == self.CalculationType.FORMULA and not self.formula:
            raise ValidationError(
                {"formula": _("Formula is required when calculation_type=FORMULA.")}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================================================================
# 2. SALARY STRUCTURE  (employee-wise, revision-tracked)
# ===========================================================================

class SalaryStructure(BaseModel):
    """
    Employee-specific salary package tied to an effective date.

    Revision logic (enforced in save()):
      - When a new revision is saved, the most-recent open revision for
        the same employee has its end_date set to (new.effective_date - 1 day).
      - Overlapping windows are rejected in clean().
    """

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="salary_structures",
    )
    ctc = models.DecimalField(**MONEY, help_text=_("Annual CTC in INR"))
    gross_salary = models.DecimalField(**MONEY, help_text=_("Monthly gross"))
    basic_salary = models.DecimalField(**MONEY, help_text=_("Monthly basic"))
    effective_date = models.DateField()
    end_date = models.DateField(
        null=True, blank=True,
        help_text=_("Auto-set when the next revision is saved"),
    )
    revision_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-effective_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "effective_date"],
                name="uq_salary_structure_employee_date",
            )
        ]
        indexes = [
            # Fast lookup: all revisions for an employee ordered by date
            models.Index(
                fields=["employee", "effective_date"],
                name="ix_salstruct_emp_effdate",
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee} | Gross ₹{self.gross_salary} "
            f"(w.e.f. {self.effective_date})"
        )

    def clean(self):
        if self.basic_salary and self.gross_salary:
            if self.basic_salary > self.gross_salary:
                raise ValidationError(
                    {"basic_salary": _("Basic salary cannot exceed gross salary.")}
                )

        # Overlap guard — skip for existing record being updated in-place
        qs = SalaryStructure.objects.filter(
            employee=self.employee, is_active=True,
        ).exclude(pk=self.pk)

        for rev in qs:
            w_start = rev.effective_date
            w_end = rev.end_date  # None = open-ended

            if w_end is None:
                if self.effective_date < w_start:
                    raise ValidationError(
                        _(
                            f"Cannot insert a revision on {self.effective_date} "
                            f"because a newer open revision exists from {w_start}."
                        )
                    )
            else:
                if w_start <= self.effective_date <= w_end:
                    raise ValidationError(
                        _(
                            f"Effective date overlaps with revision "
                            f"{w_start} – {w_end}."
                        )
                    )

    @transaction.atomic
    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.pk:
            # Auto-close the previous open revision for this employee
            prev = (
                SalaryStructure.objects.filter(
                    employee=self.employee,
                    is_active=True,
                    end_date__isnull=True,
                    effective_date__lt=self.effective_date,
                )
                .order_by("-effective_date")
                .first()
            )
            if prev:
                prev.end_date = self.effective_date - datetime.timedelta(days=1)
                # Use update() to bypass full_clean on prev (only changing end_date)
                SalaryStructure.objects.filter(pk=prev.pk).update(
                    end_date=prev.end_date
                )
        super().save(*args, **kwargs)


# ===========================================================================
# 3. SALARY STRUCTURE ITEMS
# ===========================================================================

class SalaryStructureItem(BaseModel):
    """Links a SalaryComponent to a SalaryStructure with its resolved value."""

    salary_structure = models.ForeignKey(
        SalaryStructure, on_delete=models.CASCADE, related_name="items",
    )
    component = models.ForeignKey(
        SalaryComponent, on_delete=models.PROTECT, related_name="structure_items",
    )
    fixed_amount = models.DecimalField(
        **MONEY, default=Decimal("0.00"),
        help_text=_("Required when component.calculation_type=FIXED"),
    )
    percentage = models.DecimalField(
        max_digits=6, decimal_places=4, default=Decimal("0.0000"),
        help_text=_("% of basic. Required when calculation_type=PERCENTAGE"),
    )
    # Safe-engine only — never eval'd directly
    formula_override = models.TextField(
        blank=True,
        help_text=_(
            "Employee-level formula override. "
            "Processed by payroll.engine only — never eval'd directly."
        ),
    )

    class Meta:
        ordering = ["component__display_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["salary_structure", "component"],
                name="uq_salstructitem_struct_comp",
            )
        ]

    def __str__(self):
        return f"{self.salary_structure.employee} | {self.component.name}"

    def clean(self):
        calc = self.component.calculation_type if self.component_id else None

        if calc == SalaryComponent.CalculationType.FIXED:
            if not self.fixed_amount or self.fixed_amount <= Decimal("0.00"):
                raise ValidationError(
                    {"fixed_amount": _("A positive fixed amount is required for FIXED components.")}
                )

        elif calc == SalaryComponent.CalculationType.PERCENTAGE:
            if not self.percentage or self.percentage <= Decimal("0.0000"):
                raise ValidationError(
                    {"percentage": _("A positive percentage is required for PERCENTAGE components.")}
                )

        elif calc == SalaryComponent.CalculationType.FORMULA:
            effective_formula = self.formula_override or (
                self.component.formula if self.component_id else ""
            )
            if not effective_formula:
                raise ValidationError(
                    {"formula_override": _(
                        "A formula is required for FORMULA components. "
                        "Set it on the component or provide a formula_override."
                    )}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================================================================
# 4. PAYROLL RUN
# ===========================================================================

class PayrollRun(BaseModel):
    """Monthly payroll batch. Lifecycle: DRAFT → PROCESSING → FINALIZED → PAID."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        PROCESSING = "PROCESSING", _("Processing")
        FINALIZED = "FINALIZED", _("Finalized")
        PAID = "PAID", _("Paid")

    class Month(models.IntegerChoices):
        JANUARY = 1, _("January")
        FEBRUARY = 2, _("February")
        MARCH = 3, _("March")
        APRIL = 4, _("April")
        MAY = 5, _("May")
        JUNE = 6, _("June")
        JULY = 7, _("July")
        AUGUST = 8, _("August")
        SEPTEMBER = 9, _("September")
        OCTOBER = 10, _("October")
        NOVEMBER = 11, _("November")
        DECEMBER = 12, _("December")

    month = models.PositiveSmallIntegerField(choices=Month.choices, db_index=True)
    year = models.PositiveSmallIntegerField(db_index=True)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="payroll_runs",
    )
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.DRAFT, db_index=True,
    )
    total_employees = models.PositiveIntegerField(default=0)
    total_gross = models.DecimalField(**MONEY, default=Decimal("0.00"))
    total_deductions = models.DecimalField(**MONEY, default=Decimal("0.00"))
    total_net = models.DecimalField(**MONEY, default=Decimal("0.00"))
    remarks = models.TextField(blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "month", "year", "department"],
                name="uq_payrollrun_org_month_year_dept",
            )
        ]
        indexes = [
            # Dashboard: filter by month + year + status
            models.Index(
                fields=["month", "year", "status"],
                name="ix_payrun_mo_yr_status",
            ),
        ]

    def __str__(self):
        dept = f" [{self.department}]" if self.department else " [All Departments]"
        return (
            f"Payroll {self.get_month_display()} {self.year}{dept}"
            f" — {self.get_status_display()}"
        )

    @property
    def is_locked(self):
        return self.status in (self.Status.FINALIZED, self.Status.PAID)

    def clean(self):
        current_year = timezone.now().year
        if self.year and not (2000 <= self.year <= current_year + 1):
            raise ValidationError(
                {"year": _("Year must be between 2000 and next calendar year.")}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================================================================
# 5. EMPLOYEE PAYSLIP
# ===========================================================================

class EmployeePayslip(BaseModel):
    """One payslip per employee per PayrollRun. Immutable once FINALIZED/PAID."""

    class Status(models.TextChoices):
        DRAFT = "DRAFT", _("Draft")
        GENERATED = "GENERATED", _("Generated")
        FINALIZED = "FINALIZED", _("Finalized")
        PAID = "PAID", _("Paid")
        CANCELLED = "CANCELLED", _("Cancelled")

    payroll_run = models.ForeignKey(
        PayrollRun, on_delete=models.CASCADE, related_name="payslips",
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="payslips",
    )
    total_working_days = models.PositiveSmallIntegerField(default=0)
    paid_days = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    lop_days = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    overtime_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("0.00"))
    gross_earnings = models.DecimalField(**MONEY, default=Decimal("0.00"))
    total_deductions = models.DecimalField(**MONEY, default=Decimal("0.00"))
    overtime_amount = models.DecimalField(**MONEY, default=Decimal("0.00"))
    net_salary = models.DecimalField(**MONEY, default=Decimal("0.00"))
    status = models.CharField(
        max_length=20, choices=Status.choices,
        default=Status.DRAFT, db_index=True,
    )
    payment_date = models.DateField(null=True, blank=True)
    payment_mode = models.CharField(max_length=30, blank=True)
    transaction_reference = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["employee__employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["payroll_run", "employee"],
                name="uq_payslip_run_employee",
            )
        ]
        indexes = [
            # Primary payroll query: all payslips for a run
            models.Index(
                fields=["payroll_run", "employee"],
                name="ix_payslip_run_employee",
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee} | "
            f"{self.payroll_run.get_month_display()} {self.payroll_run.year} | "
            f"Net ₹{self.net_salary}"
        )

    @property
    def is_locked(self):
        return self.status in (self.Status.FINALIZED, self.Status.PAID)

    def clean(self):
        # Immutability guard
        if self.pk:
            try:
                original = EmployeePayslip.objects.get(pk=self.pk)
                if original.is_locked:
                    raise ValidationError(
                        _(
                            f"Payslip is locked "
                            f"(status: {original.get_status_display()}) "
                            "and cannot be modified."
                        )
                    )
            except EmployeePayslip.DoesNotExist:
                pass

        if self.net_salary is not None and self.net_salary < Decimal("0.00"):
            raise ValidationError({"net_salary": _("Net salary cannot be negative.")})

        if (
            self.lop_days is not None
            and self.total_working_days
            and self.lop_days > self.total_working_days
        ):
            raise ValidationError(
                {"lop_days": _("LOP days cannot exceed total working days.")}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================================================================
# 6. PAYSLIP ITEMS
# ===========================================================================

class PayslipItem(BaseModel):
    """Granular earning/deduction line on a payslip."""

    class ItemType(models.TextChoices):
        EARNING = "EARNING", _("Earning")
        DEDUCTION = "DEDUCTION", _("Deduction")

    payslip = models.ForeignKey(
        EmployeePayslip, on_delete=models.CASCADE, related_name="items",
    )
    component = models.ForeignKey(
        SalaryComponent, on_delete=models.PROTECT, related_name="payslip_items",
    )
    item_type = models.CharField(max_length=20, choices=ItemType.choices)
    amount = models.DecimalField(**MONEY, default=Decimal("0.00"))
    calculation_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["component__display_order"]

    def __str__(self):
        return f"{self.payslip.employee} | {self.component.name} ₹{self.amount}"

    def clean(self):
        # Amount must not be negative
        if self.amount is not None and self.amount < Decimal("0.00"):
            raise ValidationError({"amount": _("Payslip item amount cannot be negative.")})

        # item_type must match the component's component_type
        if self.component_id:
            expected = self.component.component_type
            if self.item_type and self.item_type != expected:
                raise ValidationError(
                    {
                        "item_type": _(
                            f"item_type '{self.item_type}' does not match "
                            f"component type '{expected}' for {self.component.code}."
                        )
                    }
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================================================================
# 7. EMPLOYEE LOAN
# ===========================================================================

class EmployeeLoan(BaseModel):
    """Employee loan / salary advance with EMI-based recovery schedule."""

    class LoanType(models.TextChoices):
        SALARY_ADVANCE = "SALARY_ADVANCE", _("Salary Advance")
        PERSONAL_LOAN = "PERSONAL_LOAN", _("Personal Loan")
        EMERGENCY_LOAN = "EMERGENCY_LOAN", _("Emergency Loan")
        VEHICLE_LOAN = "VEHICLE_LOAN", _("Vehicle Loan")
        HOUSING_LOAN = "HOUSING_LOAN", _("Housing Loan")
        OTHER = "OTHER", _("Other")

    class LoanStatus(models.TextChoices):
        PENDING_APPROVAL = "PENDING_APPROVAL", _("Pending Approval")
        APPROVED = "APPROVED", _("Approved")
        ACTIVE = "ACTIVE", _("Active")
        CLOSED = "CLOSED", _("Closed")
        REJECTED = "REJECTED", _("Rejected")
        WRITTEN_OFF = "WRITTEN_OFF", _("Written Off")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="loans",
    )
    loan_type = models.CharField(max_length=30, choices=LoanType.choices)
    loan_number = models.CharField(max_length=30, unique=True)
    principal_amount = models.DecimalField(**MONEY)
    emi_amount = models.DecimalField(**MONEY)
    outstanding_amount = models.DecimalField(**MONEY)
    interest_rate = models.DecimalField(
        max_digits=6, decimal_places=4, default=Decimal("0.0000"),
    )
    disbursement_date = models.DateField()
    tenure_months = models.PositiveSmallIntegerField()
    first_emi_month = models.PositiveSmallIntegerField(choices=PayrollRun.Month.choices)
    first_emi_year = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=30, choices=LoanStatus.choices,
        default=LoanStatus.PENDING_APPROVAL, db_index=True,
    )
    approval_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-disbursement_date"]

    def __str__(self):
        return (
            f"[{self.loan_number}] {self.employee} | "
            f"{self.get_loan_type_display()} ₹{self.principal_amount} "
            f"(Outstanding: ₹{self.outstanding_amount})"
        )

    def clean(self):
        if self.principal_amount is not None and self.outstanding_amount is not None:
            if self.outstanding_amount > self.principal_amount:
                raise ValidationError(
                    {"outstanding_amount": _(
                        "Outstanding (₹%(out)s) cannot exceed principal (₹%(prin)s)."
                    ) % {"out": self.outstanding_amount, "prin": self.principal_amount}}
                )
        if self.emi_amount is not None and self.outstanding_amount is not None:
            if self.emi_amount > self.outstanding_amount:
                raise ValidationError(
                    {"emi_amount": _(
                        "EMI (₹%(emi)s) cannot exceed outstanding (₹%(out)s)."
                    ) % {"emi": self.emi_amount, "out": self.outstanding_amount}}
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================================================================
# 8. LOAN INSTALLMENT
# ===========================================================================

class LoanInstallment(BaseModel):
    """One EMI row per loan month. PENDING → DEDUCTED / WAIVED / MISSED."""

    class InstallmentStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        DEDUCTED = "DEDUCTED", _("Deducted")
        WAIVED = "WAIVED", _("Waived")
        MISSED = "MISSED", _("Missed")

    loan = models.ForeignKey(
        EmployeeLoan, on_delete=models.CASCADE, related_name="installments",
    )
    installment_number = models.PositiveSmallIntegerField()
    due_month = models.PositiveSmallIntegerField(choices=PayrollRun.Month.choices)
    due_year = models.PositiveSmallIntegerField()
    emi_amount = models.DecimalField(**MONEY)
    principal_component = models.DecimalField(**MONEY, default=Decimal("0.00"))
    interest_component = models.DecimalField(**MONEY, default=Decimal("0.00"))
    balance_after_emi = models.DecimalField(**MONEY, default=Decimal("0.00"))
    status = models.CharField(
        max_length=20, choices=InstallmentStatus.choices,
        default=InstallmentStatus.PENDING, db_index=True,
    )
    payslip = models.ForeignKey(
        EmployeePayslip, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="loan_deductions",
    )
    deduction_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["installment_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["loan", "installment_number"],
                name="uq_loaninstallment_loan_num",
            )
        ]

    def __str__(self):
        return (
            f"EMI #{self.installment_number} | {self.loan.loan_number} | "
            f"{self.get_due_month_display()} {self.due_year} | "
            f"₹{self.emi_amount} [{self.get_status_display()}]"
        )

    def clean(self):
        current_year = timezone.now().year

        # Validate due_year
        if self.due_year and not (2000 <= self.due_year <= current_year + 10):
            raise ValidationError(
                {"due_year": _("Due year must be between 2000 and 10 years from now.")}
            )

        # Validate due_month
        if self.due_month and self.due_month not in range(1, 13):
            raise ValidationError(
                {"due_month": _("Due month must be between 1 (Jan) and 12 (Dec).")}
            )

        # EMI amount cannot be negative
        if self.emi_amount is not None and self.emi_amount < Decimal("0.00"):
            raise ValidationError(
                {"emi_amount": _("EMI amount cannot be negative.")}
            )

        # DEDUCTED installment must reference a payslip
        if self.status == self.InstallmentStatus.DEDUCTED and not self.payslip_id:
            raise ValidationError(
                {"payslip": _(
                    "A payslip reference is required when installment status is DEDUCTED."
                )}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


# ===========================================================================
# 9. ARREARS
# ===========================================================================

class Arrear(BaseModel):
    """Backdated salary corrections (additional pay or recovery)."""

    class ArrearType(models.TextChoices):
        EARNING = "EARNING", _("Earning (Arrear Pay)")
        DEDUCTION = "DEDUCTION", _("Deduction (Arrear Recovery)")

    class ArrearStatus(models.TextChoices):
        PENDING = "PENDING", _("Pending Processing")
        PROCESSED = "PROCESSED", _("Processed in Payroll")
        CANCELLED = "CANCELLED", _("Cancelled")

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="arrears",
    )
    component = models.ForeignKey(
        SalaryComponent, on_delete=models.PROTECT, related_name="arrears",
    )
    arrear_type = models.CharField(max_length=20, choices=ArrearType.choices)
    from_month = models.PositiveSmallIntegerField(choices=PayrollRun.Month.choices)
    from_year = models.PositiveSmallIntegerField()
    to_month = models.PositiveSmallIntegerField(choices=PayrollRun.Month.choices)
    to_year = models.PositiveSmallIntegerField()
    amount = models.DecimalField(**MONEY)
    reason = models.TextField()
    status = models.CharField(
        max_length=20, choices=ArrearStatus.choices,
        default=ArrearStatus.PENDING, db_index=True,
    )
    processed_in_payroll = models.ForeignKey(
        PayrollRun, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="arrears",
    )
    processed_payslip = models.ForeignKey(
        EmployeePayslip, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="arrears",
    )

    class Meta:
        ordering = ["-from_year", "-from_month"]

    def __str__(self):
        period = (
            f"{self.get_from_month_display()} {self.from_year} → "
            f"{self.get_to_month_display()} {self.to_year}"
        )
        return (
            f"{self.employee} | {self.get_arrear_type_display()} | "
            f"₹{self.amount} | {period}"
        )

    def clean(self):
        if self.from_year and self.to_year and self.from_month and self.to_month:
            from_period = self.from_year * 100 + self.from_month
            to_period = self.to_year * 100 + self.to_month
            if from_period > to_period:
                raise ValidationError(
                    _("Arrear 'from' period cannot be later than 'to' period.")
                )

        if self.amount is not None and self.amount <= Decimal("0.00"):
            raise ValidationError(
                {"amount": _("Arrear amount must be greater than zero.")}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
