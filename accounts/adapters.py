from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.contrib.auth import get_user_model
from django.urls import reverse

User = get_user_model()

class HRMSAccountAdapter(DefaultAccountAdapter):
    def save_user(self, request, user, form, commit=True):
        """
        When a new user is created via OAuth, allauth calls this method.
        We set the defaults exactly like the existing register flow.
        """
        user = super().save_user(request, user, form, commit=False)
        # OAuth users are not approved by default until they complete org onboarding
        user.is_approved = False
        user.is_staff = False
        
        # In allauth, if ACCOUNT_USERNAME_REQUIRED=False, it might not generate a great username.
        # Let's ensure they have one using their email prefix if missing.
        if not user.username:
            user.username = user.email.split('@')[0]
            # Ensure unique
            base_username = user.username
            counter = 1
            while User.objects.filter(username=user.username).exists():
                user.username = f"{base_username}{counter}"
                counter += 1
                
        if commit:
            user.save()
        return user

    def get_login_redirect_url(self, request):
        """
        After any OAuth login or signup, check if the user has an organization.
        If not, redirect them to org setup.

        NOTE: This is called for new OAuth account creation.
        Existing-user linking is handled by the middleware (OrganizationRequiredMiddleware)
        which enforces the same rule on every request, making it impossible to bypass.
        """
        user = request.user
        if user.is_authenticated and not getattr(user, 'organization_id', None):
            return reverse('oauth_org_setup')
        return super().get_login_redirect_url(request)

class HRMSSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """
        Invoked just after a user successfully authenticates via a social provider,
        but before the login is actually processed.

        This implements secure Account Linking: if an existing HRMS user has the
        same verified email as the OAuth provider, we link the social account to
        the existing user rather than creating a duplicate.

        After linking, the normal login flow continues and the
        OrganizationRequiredMiddleware will handle enforcement of org membership
        regardless of whether this is the first or Nth time the user logs in.
        """
        # If the social account is already linked to a user, do nothing (allauth handles it)
        if sociallogin.is_existing:
            return

        # Check if the provider gave us an email
        if 'email' not in sociallogin.account.extra_data:
            return
            
        email = sociallogin.account.extra_data.get('email', '').lower()
        if not email:
            return

        # Check if the provider considers this email verified
        # Google: 'email_verified': True
        # Microsoft: trusted if it comes via OAuth 2.0 from Microsoft
        is_verified = False
        if sociallogin.account.provider == 'google':
            is_verified = sociallogin.account.extra_data.get('email_verified') == True
        elif sociallogin.account.provider == 'microsoft':
            # Microsoft verified the email by controlling the identity provider
            is_verified = True
            
        if not is_verified:
            # We don't link unverified emails for security reasons
            return
            
        # Look for an existing user with this email
        try:
            existing_user = User.objects.get(email__iexact=email)
            # If found, link the social account to this existing user.
            # After this, allauth will log in the existing user.
            # OrganizationRequiredMiddleware will then enforce the org check.
            sociallogin.connect(request, existing_user)
        except User.DoesNotExist:
            pass  # No existing user; let allauth create a new one via save_user()
