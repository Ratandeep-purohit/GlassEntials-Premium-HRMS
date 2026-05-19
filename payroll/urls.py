from django.urls import path
from . import views

urlpatterns = [
    path('', views.payroll_dashboard, name='payroll'),
    path('salaries/', views.salary_list, name='salary_list'),
    path('create/', views.create_payroll_run, name='create_payroll_run'),
    path('run/<int:run_id>/', views.run_payroll, name='run_payroll'),
    path('run/<int:run_id>/payslips/', views.payslip_list, name='payslip_list'),
    path('payslip/<int:payslip_id>/', views.payslip_detail, name='payslip_detail'),
    path('employee-salary/<int:employee_id>/', views.manage_employee_salary, name='manage_employee_salary'),
    path('components/', views.salary_components_list, name='salary_components'),
    path('my-payslips/', views.my_payslips, name='my_payslips'),
    path('my-salary-structure/', views.my_salary_structure, name='my_salary_structure'),
    path('my-loans/', views.my_loans, name='my_loans'),
    path('my-loans/request/', views.request_loan, name='request_loan'),
    path('admin-loans/', views.admin_loans, name='admin_loans'),
    path('admin-loans/approve/<int:loan_id>/', views.admin_approve_loan, name='admin_approve_loan'),
    path('admin-loans/reject/<int:loan_id>/', views.admin_reject_loan, name='admin_reject_loan'),
    path('admin-loans/create/', views.admin_create_loan, name='admin_create_loan'),
    path('admin-arrears/', views.admin_arrears, name='admin_arrears'),
    path('admin-arrears/cancel/<int:arrear_id>/', views.admin_cancel_arrear, name='admin_cancel_arrear'),
    path('my-arrears/', views.my_arrears, name='my_arrears'),
]
