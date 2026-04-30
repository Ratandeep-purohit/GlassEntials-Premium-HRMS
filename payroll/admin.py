from django.contrib import admin
from .models import SalaryComponent, SalaryStructure, SalaryStructureComponent, EmployeeSalary, Payslip

class SalaryStructureComponentInline(admin.TabularInline):
    model = SalaryStructureComponent
    extra = 1

@admin.register(SalaryComponent)
class SalaryComponentAdmin(admin.ModelAdmin):
    list_display = ('name', 'component_type', 'is_taxable', 'is_calculated_on_attendance')
    list_filter = ('component_type', 'is_taxable')
    search_fields = ('name',)

@admin.register(SalaryStructure)
class SalaryStructureAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    inlines = [SalaryStructureComponentInline]

@admin.register(EmployeeSalary)
class EmployeeSalaryAdmin(admin.ModelAdmin):
    list_display = ('employee', 'structure', 'base_salary')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id')
    list_filter = ('structure',)

@admin.register(Payslip)
class PayslipAdmin(admin.ModelAdmin):
    list_display = ('employee', 'month', 'year', 'net_salary', 'status')
    list_filter = ('month', 'year', 'status')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id')
    readonly_fields = ('gross_salary', 'total_deductions', 'net_salary')
