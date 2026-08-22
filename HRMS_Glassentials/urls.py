"""
URL configuration for HRMS_Glassentials project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
"""
from django.contrib import admin
from django.urls import include, path, re_path
from django.conf import settings
from django.conf.urls.static import static
import os

# Admin URL is configurable via env var to prevent bot/brute-force attacks.
# In production, set DJANGO_ADMIN_URL to something random, e.g. 'xK9mP2-manage/'.
_admin_url = os.environ.get('DJANGO_ADMIN_URL', 'secret-admin/')

urlpatterns = [
    path(_admin_url, admin.site.urls),
    path('', include('accounts.urls')),
    path('home/', include('home.urls')),
    path('employees/', include('employees.urls')),
    path('payroll/', include('payroll.urls')),
    path('attendance/', include('attendance.urls')),
    path('leaves/', include('leaves.urls')),
    path('assets/', include('assets.urls')),
    path('announcements/', include('announcements.urls')),
    path('letters/', include('letters.urls')),
    path('accounts/', include('allauth.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

if not getattr(settings, 'USE_S3', False):
    from employees.views import secure_media_serve
    # Note: Using re_path to capture paths. The 'media/' prefix must match MEDIA_URL without slashes.
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$', secure_media_serve, name='secure_media_serve'),
    ]

handler400 = 'home.error_views.bad_request'
handler403 = 'home.error_views.permission_denied'
handler404 = 'home.error_views.page_not_found'
handler500 = 'home.error_views.server_error'
