from django.contrib import admin
from django.urls import path, include
from . import views
from . import user_management_views as um

urlpatterns = [
    path('', views.landing_page, name='landing_page'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('oauth-org-setup/', views.oauth_org_setup, name='oauth_org_setup'),

    # First-login password setup
    path('accounts/password-setup/', um.password_setup_view, name='password_setup'),

    # User Management (staff only)
    path('accounts/users/', um.user_management_view, name='user_management'),
    path('accounts/users/create/', um.create_user_view, name='create_user'),
    path('accounts/users/temp-creds/', um.get_temp_creds_view, name='get_temp_creds'),
    path('accounts/users/<int:user_id>/toggle-status/', um.toggle_user_status_view, name='toggle_user_status'),
    path('accounts/users/<int:user_id>/reset-password/', um.reset_user_password_view, name='reset_user_password'),
    path('accounts/users/<int:user_id>/edit-role/', um.edit_user_role_view, name='edit_user_role'),
    path('accounts/users/<int:user_id>/convert-employee/', um.convert_to_employee_view, name='convert_to_employee'),
]