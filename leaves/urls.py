from django.urls import path
from . import views

app_name = 'leaves'

urlpatterns = [
    # ESS - Employee Self Service
    path('', views.leave_dashboard_view, name='dashboard'),
    path('apply/', views.apply_leave_view, name='apply_leave'),
    path('apply-compoff/', views.apply_compoff_view, name='apply_compoff'),
    path('history/', views.leave_history_view, name='history'),
    path('cancel/<int:leave_id>/', views.request_leave_cancellation_view, name='request_cancel'),
    path('rh-picker/', views.rh_picker_view, name='rh_picker'),
    path('claim-rh/<int:holiday_id>/', views.claim_rh_view, name='claim_rh'),

    
    # Manager/HR Actions
    path('pending/', views.pending_approvals_view, name='pending_approvals'),
    path('action/<int:leave_id>/', views.approve_reject_action_view, name='leave_action'),
    path('compoff-action/<int:compoff_id>/', views.compoff_action_view, name='compoff_action'),
    path('cancel-action/<int:leave_id>/', views.cancel_approval_action_view, name='cancel_action'),

    
    # Policy & Settings
    path('calendar/', views.global_calendar_view, name='calendar'),
    
    # Reports
    path('export-leave-card/', views.export_leave_card_view, name='export_leave_card'),
]

