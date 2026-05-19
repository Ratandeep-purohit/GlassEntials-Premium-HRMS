from django.contrib import admin

from .models import (
    Arrear,
    EmployeeLoan,
    EmployeePayslip,
    LoanInstallment,
    PayrollRun,
    PayslipItem,
    SalaryComponent,
    SalaryStructure,
    SalaryStructureItem,
)


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class SalaryStructureItemInline(admin.TabularInline):
    model = SalaryStructureItem
    extra = 1
    fields = ("component", "fixed_amount", "percentage", "formula_override")
    autocomplete_fields = ["component"]


class PayslipItemInline(admin.TabularInline):
    model = PayslipItem
    extra = 0
    fields = ("component", "item_type", "amount", "calculation_note")
    readonly_fields = ("calculation_note",)


class LoanInstallmentInline(admin.TabularInline):
    model = LoanInstallment
    extra = 0
    fields = (
        "installment_number", "due_month", "due_year",
        "emi_amount", "balance_after_emi", "status", "payslip",
    )
    readonly_fields = ("installment_number",)


# ---------------------------------------------------------------------------
# SalaryComponent
# ---------------------------------------------------------------------------

@admin.register(SalaryComponent)
class SalaryComponentAdmin(admin.ModelAdmin):
    list_display = (
        "code", "name", "component_type", "calculation_type",
        "is_taxable", "is_statutory", "is_active",
    )
    list_filter = ("component_type", "calculation_type", "is_taxable", "is_statutory")
    search_fields = ("code", "name")
    ordering = ("display_order", "name")


# ---------------------------------------------------------------------------
# SalaryStructure
# ---------------------------------------------------------------------------

@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):
    list_display = (
        "employee", "gross_salary", "basic_salary",
        "ctc", "effective_date", "end_date", "is_active",
    )
    list_filter = ("is_active",)
    search_fields = (
        "employee__first_name", "employee__last_name", "employee__employee_id",
    )
    date_hierarchy = "effective_date"
    readonly_fields = ("end_date",)
    inlines = [SalaryStructureItemInline]


# ---------------------------------------------------------------------------
# PayrollRun
# ---------------------------------------------------------------------------

@admin.register(PayrollRun)
class PayrollRunAdmin(admin.ModelAdmin):
    list_display = (
        "__str__", "month", "year", "department",
        "status", "total_employees", "total_net",
    )
    list_filter = ("status", "year", "month", "department")
    readonly_fields = (
        "total_employees", "total_gross", "total_deductions",
        "total_net", "finalized_at", "paid_at",
    )


# ---------------------------------------------------------------------------
# EmployeePayslip
# ---------------------------------------------------------------------------

@admin.register(EmployeePayslip)
class EmployeePayslipAdmin(admin.ModelAdmin):
    list_display = (
        "employee", "payroll_run", "gross_earnings",
        "total_deductions", "net_salary", "status",
    )
    list_filter = ("status", "payroll_run__year", "payroll_run__month")
    search_fields = (
        "employee__first_name", "employee__last_name", "employee__employee_id",
    )
    readonly_fields = (
        "gross_earnings", "total_deductions", "net_salary",
        "overtime_amount",
    )
    inlines = [PayslipItemInline]

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_locked:
            # Make everything read-only for locked payslips
            return [f.name for f in obj._meta.fields]
        return self.readonly_fields


# ---------------------------------------------------------------------------
# EmployeeLoan
# ---------------------------------------------------------------------------

@admin.register(EmployeeLoan)
class EmployeeLoanAdmin(admin.ModelAdmin):
    list_display = (
        "loan_number", "employee", "loan_type",
        "principal_amount", "outstanding_amount", "status",
    )
    list_filter = ("loan_type", "status")
    search_fields = (
        "loan_number",
        "employee__first_name", "employee__last_name", "employee__employee_id",
    )
    inlines = [LoanInstallmentInline]


# ---------------------------------------------------------------------------
# Arrear
# ---------------------------------------------------------------------------

@admin.register(Arrear)
class ArrearAdmin(admin.ModelAdmin):
    list_display = (
        "employee", "arrear_type", "component",
        "amount", "from_month", "from_year", "status",
    )
    list_filter = ("arrear_type", "status")
    search_fields = (
        "employee__first_name", "employee__last_name", "employee__employee_id",
    )
