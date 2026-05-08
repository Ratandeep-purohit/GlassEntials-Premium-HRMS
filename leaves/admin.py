from django.contrib import admin
from .models import Location, LeaveType, LeavePolicy, LeaveBalance, LeaveRequest, ApprovalWorkflow, LeaveAccrualLog, Holiday

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'country_code', 'timezone', 'organization')
    list_filter = ('organization', 'country_code')

@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_paid', 'is_statutory', 'organization')
    list_filter = ('organization', 'is_paid', 'is_statutory')
    search_fields = ('name', 'code')

@admin.register(LeavePolicy)
class LeavePolicyAdmin(admin.ModelAdmin):
    list_display = ('leave_type', 'accrual_rate', 'max_balance', 'organization')
    list_filter = ('organization', 'leave_type')

@admin.register(LeaveBalance)
class LeaveBalanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'year', 'current_balance', 'organization')
    list_filter = ('organization', 'year', 'leave_type')

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'status', 'organization')
    list_filter = ('status', 'organization', 'leave_type')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id')

@admin.register(ApprovalWorkflow)
class ApprovalWorkflowAdmin(admin.ModelAdmin):
    list_display = ('leave_request', 'approver', 'sequence_order', 'status')
    list_filter = ('status',)

@admin.register(LeaveAccrualLog)
class LeaveAccrualLogAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'amount', 'action_type', 'created_at')
    list_filter = ('action_type', 'leave_type')

@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'location_fk', 'is_optional', 'organization')
    list_filter = ('organization', 'is_optional', 'date', 'location_fk')
    search_fields = ('name',)
