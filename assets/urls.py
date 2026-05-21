from django.urls import path
from . import views

app_name = 'assets'

urlpatterns = [
    # Admin Views
    path('', views.asset_dashboard_view, name='dashboard'),
    path('inventory/', views.inventory_list_view, name='inventory'),
    path('inventory/add/', views.add_asset_view, name='add_asset'),
    path('inventory/edit/<int:asset_id>/', views.edit_asset_view, name='edit_asset'),
    path('inventory/assign/<int:asset_id>/', views.assign_asset_view, name='assign_asset'),
    path('inventory/return/<int:assignment_id>/', views.return_asset_view, name='return_asset'),
    path('requests/', views.manage_requests_view, name='manage_requests'),
    path('requests/action/<int:request_id>/', views.request_action_view, name='request_action'),
    path('categories/', views.manage_categories_view, name='manage_categories'),

    # Employee Views
    path('my-assets/', views.my_assets_view, name='my_assets'),
    path('request/', views.request_asset_view, name='request_asset'),
]
