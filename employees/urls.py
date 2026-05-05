from django.contrib import admin
from django.urls import include, path
from employees import views as view

urlpatterns = [
    path('', view.employee_view, name='employee'),
    path('department', view.department_view, name='department'),
    path('department/edit/<int:pk>/', view.department_view, name='edit_department'),
    path('department/delete/<int:pk>/', view.delete_department, name='delete_department'),
    path('department/toggle-status/<int:pk>/', view.toggle_department_status, name='toggle_department_status'),
    path('designation',view.designation_view,name='designation'),
    path('designation/edit/<int:pk>/', view.designation_view, name='edit_designation'),
    path('designation/delete/<int:pk>/', view.delete_designation, name='delete_designation'),
    path('designation/toggle-status/<int:pk>/', view.toggle_designation_status, name='toggle_designation_status'),
    path('employee/add/', view.add_employee, name='add_employee'),
    path('employee/view/<int:pk>/', view.view_employee, name='view_employee'),
    path('employee/edit/<int:pk>/', view.edit_employee, name='edit_employee'),
    path('employee/export/csv/', view.export_employees_csv, name='export_employees_csv'),
    path('employee/export/excel/', view.export_employees_excel, name='export_employees_excel'),
    path('employee/import/', view.bulk_import, name='bulk_import'),
    path('employee/import/sample/', view.download_sample_excel, name='download_sample_excel'),
    path('employee/toggle-status/<int:pk>/', view.toggle_employee_status, name='toggle_employee_status'),
    path('employee/delete/<int:pk>/', view.delete_employee, name='delete_employee'),
    path('employee/approve/<int:pk>/', view.approve_employee, name='approve_employee'),
    path('employee/reject/<int:pk>/', view.reject_employee, name='reject_employee'),
    path('profile/edit/', view.edit_profile, name='edit_profile'),
]   