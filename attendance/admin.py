from django.contrib import admin
from .models import Shift, ShiftAssignment, AttendanceStatus, Attendance

@admin.register(Shift)
class ShiftAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_time', 'end_time', 'is_night_shift')
    search_fields = ('name',)

@admin.register(ShiftAssignment)
class ShiftAssignmentAdmin(admin.ModelAdmin):
    list_display = ('employee', 'shift', 'effective_from', 'effective_to')
    list_filter = ('shift', 'effective_from')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id')

@admin.register(AttendanceStatus)
class AttendanceStatusAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'is_paid', 'payable_day_value')

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'status', 'clock_in', 'clock_out', 'total_work_hours')
    list_filter = ('date', 'status', 'shift')
    search_fields = ('employee__first_name', 'employee__last_name', 'employee__employee_id')
    readonly_fields = ('total_work_hours', 'late_minutes')
