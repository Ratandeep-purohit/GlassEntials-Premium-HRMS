from django.contrib import admin
from .models import (
    ApprovalWorkflow,
    Holiday,
    HolidayCalendar,
    LeaveAccrualLog,
    LeaveAccrualRule,
    LeaveApproval,
    LeaveAttachment,
    LeaveAttendanceEvent,
    LeaveAuditLog,
    LeaveBalance,
    LeaveBalanceSnapshot,
    LeaveCarryForwardLog,
    LeaveCarryForwardRule,
    LeaveCategory,
    LeaveDurationRule,
    LeaveEligibilityRule,
    LeaveEncashment,
    LeaveIntegrationRule,
    LeavePayrollImpact,
    LeavePolicy,
    LeaveProofRule,
    LeaveRequest,
    LeaveRestrictionRule,
    LeaveSandwichRule,
    LeaveTransaction,
    LeaveType,
    LeaveWorkflow,
    LeaveWorkflowStep,
    Location,
)

@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ('name', 'country_code', 'timezone', 'organization')
    list_filter = ('organization', 'country_code')

@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'category', 'status', 'policy_version', 'is_paid', 'is_requestable', 'organization')
    list_filter = ('organization', 'category', 'status', 'is_paid', 'is_statutory')
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
    list_display = ('name', 'date', 'holiday_type', 'location_fk', 'is_optional', 'organization')
    list_filter = ('organization', 'holiday_type', 'is_optional', 'date', 'location_fk')
    search_fields = ('name',)

admin.site.register(LeaveCategory)
admin.site.register(LeaveAccrualRule)
admin.site.register(LeaveCarryForwardRule)
admin.site.register(LeaveEligibilityRule)
admin.site.register(LeaveRestrictionRule)
admin.site.register(LeaveDurationRule)
admin.site.register(LeaveSandwichRule)
admin.site.register(LeaveProofRule)
admin.site.register(LeaveIntegrationRule)
admin.site.register(LeaveTransaction)
admin.site.register(LeaveBalanceSnapshot)
admin.site.register(LeaveAttachment)
admin.site.register(LeaveWorkflow)
admin.site.register(LeaveWorkflowStep)
admin.site.register(LeaveApproval)
admin.site.register(HolidayCalendar)
admin.site.register(LeaveEncashment)
admin.site.register(LeaveCarryForwardLog)
admin.site.register(LeaveAttendanceEvent)
admin.site.register(LeavePayrollImpact)
admin.site.register(LeaveAuditLog)
