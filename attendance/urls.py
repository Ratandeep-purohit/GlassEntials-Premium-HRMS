from django.contrib import admin
from django.urls import include, path
from . import views

urlpatterns = [
    path('', views.attendance_view, name='attendance'),
    path('create-shift/', views.create_shift_view, name='create_shift'),
    path('assign-shift/', views.assign_shift_view, name='assign_shift'),
    path('clock-in-out/', views.clock_in_out_view, name='clock_in_out'),
    path('request-correction/<int:attendance_id>/', views.request_correction_view, name='request_correction'),
    path('manage-corrections/', views.manage_corrections_view, name='manage_corrections'),
    path('resolve-correction/<int:correction_id>/', views.resolve_correction_view, name='resolve_correction'),
    path('break-toggle/', views.break_toggle_view, name='break_toggle'),
    path('calendar/', views.attendance_calendar_view, name='attendance_calendar'),
    path('export/', views.export_attendance_view, name='export_attendance'),
]
