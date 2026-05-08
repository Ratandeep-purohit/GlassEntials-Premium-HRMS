from django.contrib import admin
from django.urls import include, path
from home import views as view

urlpatterns = [
    path('', view.home_view, name='home'),
    path('notifications/', view.notifications_view, name='notifications'),
]