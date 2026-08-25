import logging
import os
from django.shortcuts import redirect
from django.urls import reverse

logger = logging.getLogger('django')

_EXEMPT_PREFIXES = (
    '/accounts/',
    '/admin/',
    '/static/',
    '/media/',
    '/__debug__/',
)


class OrganizationRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            path = request.path_info

            if not any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
                try:
                    org_setup_url    = reverse('oauth_org_setup')
                    login_url        = reverse('login')
                    register_url     = reverse('register')
                    logout_url       = reverse('logout')
                    pwd_setup_url    = reverse('password_setup')
                except Exception:
                    org_setup_url = '/oauth-org-setup/'
                    login_url     = '/login/'
                    register_url  = '/register/'
                    logout_url    = '/logout/'
                    pwd_setup_url = '/accounts/password-setup/'

                exempt_paths = {org_setup_url, login_url, register_url, logout_url, pwd_setup_url}

                logger.info(f"[OrganizationRequiredMiddleware] Path: {path}, Exempt: {exempt_paths}")

                if path not in exempt_paths:
                    org_id = getattr(request.user, 'organization_id', None)
                    logger.info(f"[OrganizationRequiredMiddleware] User {request.user.email} org_id: {org_id}")

                    # 1. Enforce org membership
                    if not org_id:
                        logger.info("[OrganizationRequiredMiddleware] Redirecting to oauth_org_setup")
                        return redirect('oauth_org_setup')

                    # 2. Enforce first-login password setup
                    if getattr(request.user, 'must_change_password', False):
                        logger.info("[OrganizationRequiredMiddleware] Redirecting to password_setup")
                        return redirect('password_setup')

        return self.get_response(request)
