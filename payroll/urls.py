from django.urls import path
from . import views

urlpatterns = [
    path('', views.payroll_dashboard, name='payroll'),
]
