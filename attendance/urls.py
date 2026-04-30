from django.contrib import admin
from django.urls import include, path
from . import views

urlpatterns = [
    path('', views.attendance_view, name='attendance'),
    path('create-shift/', views.create_shift_view, name='create_shift'),
    path('assign-shift/', views.assign_shift_view, name='assign_shift'),
]
