from django.shortcuts import redirect
from django.urls import reverse


# URL prefixes that are always publicly accessible
_EXEMPT_PREFIXES = (
    '/accounts/',      # all allauth OAuth + callback URLs
    '/admin/',         # Django admin
    '/static/',        # static files
    '/media/',         # media files
    '/__debug__/',     # Django debug toolbar (if used)
)

# Named URL patterns that are always accessible to authenticated users
_EXEMPT_NAMES = {
    'login',
    'register',
    'logout',
    'landing_page',
    'oauth_org_setup',
    'account_login',
    'account_signup',
    'account_logout',
}


class OrganizationRequiredMiddleware:
    """
    Enforces that every authenticated user who accesses a protected HRMS URL
    must belong to an organization.

    If not, they are redirected to the OAuth org-setup page regardless of:
      - whether they logged in via email/password or OAuth
      - whether it is their first or Nth login
      - whether the adapter redirect was bypassed

    This is the server-side enforcement layer. It cannot be bypassed by
    manually typing a dashboard URL.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Only enforce for authenticated users
        if request.user.is_authenticated:
            path = request.path_info

            # Skip exempt URL prefixes
            if not any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
                # Skip exempt named views
                try:
                    org_setup_url = reverse('oauth_org_setup')
                    login_url = reverse('login')
                    register_url = reverse('register')
                    logout_url = reverse('logout')
                except Exception:
                    org_setup_url = '/oauth-org-setup/'
                    login_url = '/login/'
                    register_url = '/register/'
                    logout_url = '/logout/'

                exempt_paths = {org_setup_url, login_url, register_url, logout_url}

                if path not in exempt_paths:
                    # Check organization membership
                    if not getattr(request.user, 'organization_id', None):
                        return redirect('oauth_org_setup')

        return self.get_response(request)
