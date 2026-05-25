from django.urls import path

from . import views

app_name = 'announcements'

urlpatterns = [
    path('', views.announcement_list, name='list'),
    path('<int:announcement_id>/', views.announcement_detail, name='detail'),
    path('manage/', views.manage_announcements, name='manage'),
    path('manage/<int:announcement_id>/', views.manage_announcements, name='edit'),
    path('manage/<int:announcement_id>/delete/', views.delete_announcement, name='delete'),
    path('manage/<int:announcement_id>/toggle/', views.toggle_announcement, name='toggle'),
]

