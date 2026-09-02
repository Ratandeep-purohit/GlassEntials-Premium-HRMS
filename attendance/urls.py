from django.contrib import admin
from django.urls import include, path
from . import views

urlpatterns = [
    path('', views.attendance_view, name='attendance'),
    path('visual/', views.attendance_visual_view, name='attendance_visual'),
    path('create-shift/', views.create_shift_view, name='create_shift'),
    path('assign-shift/', views.assign_shift_view, name='assign_shift'),
    path('clock-in-out/', views.clock_in_out_view, name='clock_in_out'),
    path('request-correction/<int:attendance_id>/', views.request_correction_view, name='request_correction'),
    path('manage-corrections/', views.manage_corrections_view, name='manage_corrections'),
    path('resolve-correction/<int:correction_id>/', views.resolve_correction_view, name='resolve_correction'),
    path('break-toggle/', views.break_toggle_view, name='break_toggle'),
    path('calendar/', views.attendance_calendar_view, name='attendance_calendar'),
    path('export/', views.export_attendance_view, name='export_attendance'),
    path('analytics/', views.attendance_analytics_view, name='attendance_analytics'),
    path('overtime/', views.overtime_dashboard_view, name='overtime_dashboard'),
    path('overtime/action/<int:request_id>/', views.overtime_action_view, name='overtime_action'),
    # Admin overrides
    path('settings/', views.attendance_settings_view, name='attendance_settings'),
    path('admin/create/<int:employee_id>/', views.admin_attendance_create_view, name='admin_attendance_create'),
    path('admin/edit/<int:attendance_id>/', views.admin_attendance_edit_view, name='admin_attendance_edit'),
    path('admin/history/<int:attendance_id>/', views.admin_attendance_history_view, name='admin_attendance_history'),
    # Bulk Excel export / import
    path('export-template/', views.export_monthly_template_view, name='export_monthly_template'),
    path('import/', views.import_attendance_view, name='import_attendance'),
    path('import/preview/', views.import_attendance_preview_view, name='import_attendance_preview'),
    path('import/confirm/', views.import_attendance_confirm_view, name='import_attendance_confirm'),
    path('import/history/', views.import_attendance_history_view, name='import_attendance_history'),
]
