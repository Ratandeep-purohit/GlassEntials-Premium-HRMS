from django.urls import path

from . import views

app_name = 'letters'

urlpatterns = [
    path('', views.manage_letters, name='manage'),
    path('create/', views.letter_builder, name='create'),
    path('<int:letter_id>/', views.letter_detail, name='detail'),
    path('<int:letter_id>/edit/', views.letter_builder, name='edit'),
    path('<int:letter_id>/delete/', views.delete_letter, name='delete'),
]
