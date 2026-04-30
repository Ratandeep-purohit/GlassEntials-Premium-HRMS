from django.contrib import admin
from .models import LeaveType, LeaveRequest, Holiday

@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_paid', 'total_days_per_year', 'organization')
    list_filter = ('organization', 'is_paid')
    search_fields = ('name', 'code')

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'leave_type', 'start_date', 'end_date', 'status', 'organization')
    list_filter = ('status', 'organization', 'leave_type')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id')
    
    def save_model(self, request, obj, form, change):
        if not obj.pk:
            obj.organization = obj.employee.organization
        super().save_model(request, obj, form, change)

@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'is_optional', 'organization')
    list_filter = ('organization', 'is_optional', 'date')
    search_fields = ('name',)
