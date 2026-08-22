from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
from django.core.cache import cache

user=get_user_model()

def landing_page(request):
    return render(request,'landing_page.html')

def get_client_ip(request):
    """
    Safely extract the real client IP.
    Our Nginx configuration guarantees HTTP_X_REAL_IP is set to the 
    TCP connection's $remote_addr before proxying to Gunicorn on 127.0.0.1:8001.
    """
    x_real_ip = request.META.get('HTTP_X_REAL_IP')
    if x_real_ip:
        return x_real_ip
    return request.META.get('REMOTE_ADDR')

def login_view(request):
    ip = get_client_ip(request)
    
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        
        # Dual-bucket rate limiting strategy
        # 1. Limit specific account brute-forcing from a specific IP (Scenario A)
        cache_key_user_ip = f'login_{username}_{ip}'
        # 2. Limit general horizontal brute-forcing across many accounts from one IP (Scenario C)
        # Higher limit allows legitimate users behind the same NAT to still log in (Scenario E)
        cache_key_ip = f'login_{ip}'
        
        attempts_user_ip = cache.get(cache_key_user_ip, 0)
        attempts_ip = cache.get(cache_key_ip, 0)
        
        if attempts_user_ip >= 5 or attempts_ip >= 20:
            messages.error(request, "Too many login attempts. Please try again in 15 minutes.")
            return render(request, 'login.html')

        password = request.POST.get('password', '')
        user_auth = authenticate(request, username=username, password=password)
        if user_auth is not None:
            # Clear lockout for this specific user/IP pair on success
            cache.delete(cache_key_user_ip)
            
            if not user_auth.is_approved:
                messages.warning(request, "Your account is currently pending approval by HR/Admin.")
                return redirect('login')
            
            login(request, user_auth)
            messages.success(request, f"Welcome back, {user_auth.username}!")
            # If this user has no organization (e.g. an OAuth user who was linked
            # but never completed org setup), send them to org setup.
            if not getattr(user_auth, 'organization_id', None):
                return redirect('oauth_org_setup')
            return redirect('home')
        else:
            # Increment failed attempts
            cache.set(cache_key_user_ip, attempts_user_ip + 1, 900) # 15 minutes
            cache.set(cache_key_ip, attempts_ip + 1, 900)
            messages.error(request, "Invalid username or password.")
            return redirect('login')
            
    return render(request, 'login.html')


def _split_owner_name(username):
    cleaned_username = (username or '').replace('_', ' ').replace('.', ' ').strip()
    parts = [part for part in cleaned_username.split() if part]
    if not parts:
        return 'Owner', ''
    if len(parts) == 1:
        return parts[0].title(), ''
    return parts[0].title(), ' '.join(parts[1:]).title()


def _owner_employee_id(organization):
    owner_id = f"OWNER-{organization.id}"
    if len(owner_id) <= 20:
        return owner_id
    return f"OWN-{str(organization.id)[-16:]}"


def _create_owner_employee(new_user, organization):
    from employees.models import Department, Designation, Employee

    department, _ = Department.objects.get_or_create(
        organization=organization,
        name='Management',
        defaults={
            'description': 'Default department for organization owner.',
            'created_by': new_user,
        },
    )
    if department.is_deleted or not department.is_active:
        department.is_deleted = False
        department.is_active = True
        department.updated_by = new_user
        department.save()

    designation, _ = Designation.objects.get_or_create(
        organization=organization,
        name='Owner',
        defaults={
            'department': department,
            'description': 'Organization owner.',
            'created_by': new_user,
        },
    )
    if designation.is_deleted or not designation.is_active or designation.department_id != department.id:
        designation.is_deleted = False
        designation.is_active = True
        designation.department = department
        designation.updated_by = new_user
        designation.save()

    first_name, last_name = _split_owner_name(new_user.username)
    employee, created = Employee.objects.get_or_create(
        organization=organization,
        email=new_user.email,
        defaults={
            'employee_id': _owner_employee_id(organization),
            'first_name': first_name,
            'last_name': last_name,
            'phone_number': new_user.phone or '',
            'joining_date': timezone.localdate(),
            'employment_type': 'Full Time',
            'department': department,
            'designation': designation,
            'work_location': organization.name,
            'current_address': 'Not provided',
            'permanent_address': 'Not provided',
            'created_by': new_user,
        },
    )

    if not created:
        employee.first_name = employee.first_name or first_name
        employee.last_name = employee.last_name or last_name
        employee.phone_number = employee.phone_number or new_user.phone or ''
        employee.department = employee.department or department
        employee.designation = employee.designation or designation
        employee.is_active = True
        employee.is_deleted = False
        employee.updated_by = new_user
        employee.save()

    return employee


def register_view(request):
    ip = get_client_ip(request)
    cache_key_ip = f'register_attempts_{ip}'
    attempts_ip = cache.get(cache_key_ip, 0)
    
    if attempts_ip >= 5:
        messages.error(request, "Too many registration attempts. Please try again in 15 minutes.")
        return render(request, 'register.html')

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        email = request.POST.get('email', '').strip()
        phone = request.POST.get('phone')
        org_choice = request.POST.get('organization')
        org_name = request.POST.get('org_name')
        org_code = request.POST.get('org_code')
        password = request.POST.get('password')
        
        if user.objects.filter(username=username).exists():
            cache.set(cache_key_ip, attempts_ip + 1, 900)
            messages.error(request, "Username already exists.")
            return redirect('register')
        if user.objects.filter(email=email).exists():
            cache.set(cache_key_ip, attempts_ip + 1, 900)
            messages.error(request, "Email already exists.")
            return redirect('register')
            
        from .models import Organization
        import uuid
        
        try:
            with transaction.atomic():
                if org_choice == 'org1':
                    if not org_name:
                        messages.error(request, "Organization name is required.")
                        return redirect('register')
                    unique_code = f"{org_name[:4].upper()}-{str(uuid.uuid4())[:6].upper()}"
                    org_instance = Organization.objects.create(name=org_name, unique_code=unique_code)
                elif org_choice == 'org2':
                    if not org_code:
                        messages.error(request, "Organization unique code is required.")
                        return redirect('register')
                    try:
                        org_instance = Organization.objects.get(unique_code=org_code)
                    except Organization.DoesNotExist:
                        cache.set(cache_key_ip, attempts_ip + 1, 900)
                        messages.error(request, "Invalid organization code.")
                        return redirect('register')
                else:
                    messages.error(request, "Please select an organization setup.")
                    return redirect('register')

                # Create user
                new_user = user.objects.create_user(username=username, email=email, password=password, phone=phone)
                new_user.organization = org_instance
                
                if org_choice == 'org1':
                    new_user.is_approved = True
                    new_user.is_staff = True # Org creator is an HR Admin for their tenant
                    new_user.save()
                    _create_owner_employee(new_user, org_instance)
                    messages.success(request, "Organization, Owner account, and Owner employee profile created successfully! Please login.")
                else:
                    new_user.is_approved = False
                    new_user.is_staff = False
                    new_user.save()
                    messages.success(request, "Account created successfully! Please wait for HR/Admin to approve your account.")
                
                cache.delete(cache_key_ip) # clear on success
        except Exception as exc:
            cache.set(cache_key_ip, attempts_ip + 1, 900)
            messages.error(request, f"Account setup failed: {exc}")
            return redirect('register')

        return redirect('login')
        
    return render(request, 'register.html')

def error_404(request, exception):
    from home.error_views import page_not_found
    return page_not_found(request, exception)

def error_500(request):
    from home.error_views import server_error
    return server_error(request)

def logout_view(request):
    logout(request)
    messages.info(request, "You have been logged out.")
    return redirect('login')

from django.contrib.auth.decorators import login_required

@login_required
def oauth_org_setup(request):
    """
    Called when a user signs in via OAuth but hasn't chosen an organization yet.
    Re-uses the existing logic from register_view to create/join an org.
    """
    user_obj = request.user
    if getattr(user_obj, 'organization_id', None) is not None:
        return redirect('home')

    if request.method == 'POST':
        org_choice = request.POST.get('organization')
        org_name = request.POST.get('org_name')
        org_code = request.POST.get('org_code')
        phone = request.POST.get('phone')

        from .models import Organization
        import uuid
        
        try:
            with transaction.atomic():
                if org_choice == 'org1':
                    if not org_name:
                        messages.error(request, "Organization name is required.")
                        return redirect('oauth_org_setup')
                    unique_code = f"{org_name[:4].upper()}-{str(uuid.uuid4())[:6].upper()}"
                    org_instance = Organization.objects.create(name=org_name, unique_code=unique_code)
                elif org_choice == 'org2':
                    if not org_code:
                        messages.error(request, "Organization unique code is required.")
                        return redirect('oauth_org_setup')
                    try:
                        org_instance = Organization.objects.get(unique_code=org_code)
                    except Organization.DoesNotExist:
                        messages.error(request, "Invalid organization code.")
                        return redirect('oauth_org_setup')
                else:
                    messages.error(request, "Please select an organization setup.")
                    return redirect('oauth_org_setup')

                if phone:
                    user_obj.phone = phone

                user_obj.organization = org_instance
                
                if org_choice == 'org1':
                    user_obj.is_approved = True
                    user_obj.is_staff = True
                    user_obj.save()
                    _create_owner_employee(user_obj, org_instance)
                    messages.success(request, "Organization created successfully! Welcome.")
                    return redirect('home')
                else:
                    user_obj.is_approved = False
                    user_obj.is_staff = False
                    user_obj.save()
                    logout(request) # They are not approved yet
                    messages.success(request, "Successfully joined organization! Please wait for HR/Admin to approve your account.")
                    return redirect('login')
                
        except Exception as exc:
            messages.error(request, f"Setup failed: {exc}")
            return redirect('oauth_org_setup')

    return render(request, 'oauth_org_setup.html')
