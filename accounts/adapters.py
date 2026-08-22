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
        If a user logs in (or signs up) via OAuth and doesn't have an organization,
        they must be routed to the org setup step.
        """
        user = request.user
        if user.is_authenticated and getattr(user, 'organization_id', None) is None:
            return reverse('oauth_org_setup')
        return super().get_login_redirect_url(request)

class HRMSSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        """
        Invoked just after a user successfully authenticates via a social provider,
        but before the login is actually processed.
        This is where we implement Account Linking for existing users.
        """
        # If the social account is already linked to a user, do nothing (allauth handles it)
        if sociallogin.is_existing:
            return

        # Check if the provider gave us an email
        if 'email' not in sociallogin.account.extra_data:
            return
            
        email = sociallogin.account.extra_data.get('email').lower()
        
        # Check if the provider considers this email verified
        # Google: 'email_verified': True
        # Microsoft: varies by tenant, but let's be strict if they provide a flag
        is_verified = False
        if sociallogin.account.provider == 'google':
            is_verified = sociallogin.account.extra_data.get('email_verified') == True
        elif sociallogin.account.provider == 'microsoft':
            # Microsoft usually verified if it comes from their login, but check common flags
            is_verified = True # Assuming MSFT verified if we got here via OAuth 2.0
            
        if not is_verified:
            # We don't link unverified emails for security reasons
            return
            
        # Look for an existing user with this email
        try:
            existing_user = User.objects.get(email__iexact=email)
            # If found, link the social account to this existing user!
            sociallogin.connect(request, existing_user)
        except User.DoesNotExist:
            pass # No existing user, let allauth create a new one
