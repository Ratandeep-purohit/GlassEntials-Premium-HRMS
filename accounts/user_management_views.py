import secrets
import string
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Q
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from employees.models import Employee, Department, Designation
from attendance.models import Shift, ShiftAssignment
import uuid

User = get_user_model()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _staff_required(request):
    """Return True if the request user is authenticated, approved, and staff."""
    return (
        request.user.is_authenticated
        and request.user.is_staff
        and request.user.is_approved
    )


def _generate_temp_password(length=12):
    """Generate a cryptographically secure temporary password."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    while True:
        pwd = ''.join(secrets.choice(alphabet) for _ in range(length))
        # Ensure it has at least one of each required class
        has_upper  = any(c.isupper() for c in pwd)
        has_lower  = any(c.islower() for c in pwd)
        has_digit  = any(c.isdigit() for c in pwd)
        has_symbol = any(c in "!@#$%^&*" for c in pwd)
        if has_upper and has_lower and has_digit and has_symbol:
            return pwd


def _org_users(organization):
    """Return all CustomUser objects belonging to an organization."""
    return User.objects.filter(organization=organization).order_by('-date_joined')


def _linked_employee(user_obj):
    """Return the Employee record linked to a user by email, or None."""
    return Employee.all_objects.filter(
        organization=user_obj.organization,
        email__iexact=user_obj.email,
    ).first()


# ─── Middleware enforcement ──────────────────────────────────────────────────
# (Handled in middleware.py via must_change_password check)


# ─── Password Setup Flow ─────────────────────────────────────────────────────

@login_required
def password_setup_view(request):
    """Force first-login password creation."""
    user = request.user

    # If setup not required, go home
    if not user.must_change_password:
        return redirect('home')

    errors = []
    if request.method == 'POST':
        new_password     = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        if new_password != confirm_password:
            errors.append("Passwords do not match.")
        else:
            try:
                validate_password(new_password, user)
            except ValidationError as e:
                errors.extend(e.messages)

        if not errors:
            user.set_password(new_password)
            user.must_change_password = False
            user.save()
            # Keep user logged in after password change
            update_session_auth_hash(request, user)
            messages.success(request, "Password created successfully. Welcome to MULZON HRMS!")
            return redirect('home')

    return render(request, 'accounts/password_setup.html', {'errors': errors})


# ─── User Management ─────────────────────────────────────────────────────────

@login_required
def user_management_view(request):
    """Main User Management page — staff only."""
    if not _staff_required(request):
        messages.error(request, "You do not have permission to access User Management.")
        return redirect('home')

    org = request.user.organization
    qs  = _org_users(org)

    # Search
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )

    # Role filter
    role_filter = request.GET.get('role', '')
    if role_filter == 'staff':
        qs = qs.filter(is_staff=True)
    elif role_filter == 'employee':
        qs = qs.filter(is_staff=False)

    # Status filter
    status_filter = request.GET.get('status', '')
    if status_filter == 'active':
        qs = qs.filter(is_active=True, is_approved=True)
    elif status_filter == 'inactive':
        qs = qs.filter(is_active=False)
    elif status_filter == 'pending':
        qs = qs.filter(is_approved=False)

    # Password setup filter
    pwd_filter = request.GET.get('pwd', '')
    if pwd_filter == 'pending':
        qs = qs.filter(must_change_password=True)
    elif pwd_filter == 'done':
        qs = qs.filter(must_change_password=False)

    # Attach linked employee to each user
    all_users = list(qs)
    for u in all_users:
        u.linked_employee = _linked_employee(u)

    # Stats (unfiltered, per org)
    all_org = _org_users(org)
    total_count    = all_org.count()
    active_count   = all_org.filter(is_active=True, is_approved=True).count()
    pending_count  = all_org.filter(must_change_password=True).count()
    inactive_count = all_org.filter(Q(is_active=False) | Q(is_approved=False)).count()

    # Available employees without existing accounts (for create user form)
    existing_emails = set(all_org.exclude(email='').values_list('email', flat=True))
    available_employees = Employee.objects.filter(
        organization=org,
        is_active=True,
        is_deleted=False,
    ).exclude(email__in=existing_emails).order_by('first_name')

    # Data for "Convert to Employee" modal
    departments = Department.objects.filter(organization=org, is_active=True, is_deleted=False)
    designations = Designation.objects.filter(organization=org, is_active=True, is_deleted=False)
    shifts = Shift.objects.filter(organization=org, is_active=True, is_deleted=False)

    context = {
        'org_users': all_users,
        'search': search,
        'role_filter': role_filter,
        'status_filter': status_filter,
        'pwd_filter': pwd_filter,
        'total_count': total_count,
        'active_count': active_count,
        'pending_count': pending_count,
        'inactive_count': inactive_count,
        'available_employees': available_employees,
        'departments': departments,
        'designations': designations,
        'shifts': shifts,
    }
    return render(request, 'accounts/user_management.html', context)


@login_required
@require_POST
def create_user_view(request):
    """Create a new org user with a temporary password."""
    if not _staff_required(request):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    org = request.user.organization

    employee_id = request.POST.get('employee_id', '').strip()
    email       = request.POST.get('email', '').strip().lower()
    username    = request.POST.get('username', '').strip().lower()
    role        = request.POST.get('role', 'employee')  # 'staff' or 'employee'
    first_name  = request.POST.get('first_name', '').strip()
    last_name   = request.POST.get('last_name', '').strip()

    errors = []
    if not email:
        errors.append("Email is required.")
    if not username:
        errors.append("Username is required.")
    if User.objects.filter(username=username).exists():
        errors.append(f"Username '{username}' is already taken.")
    if User.objects.filter(email=email).exists():
        errors.append(f"A user with email '{email}' already exists.")

    # If linked to an employee, prefill name
    employee = None
    if employee_id:
        try:
            employee = Employee.objects.get(pk=employee_id, organization=org)
            if not first_name:
                first_name = employee.first_name
            if not last_name:
                last_name = employee.last_name
            if not email:
                email = employee.email
        except Employee.DoesNotExist:
            errors.append("Selected employee not found.")

    if errors:
        messages.error(request, " ".join(errors))
        return redirect('user_management')

    temp_password = _generate_temp_password()

    new_user = User.objects.create_user(
        username=username,
        email=email,
        password=temp_password,
        first_name=first_name,
        last_name=last_name,
    )

    # Ensure the linked employee has the same email so they stay linked
    if employee:
        employee.email = email
        employee.save(update_fields=['email'])
    new_user.organization     = org
    new_user.is_approved      = True
    new_user.is_staff         = (role == 'staff')
    new_user.must_change_password = True
    new_user.save()

    # Store temp creds in session once (never persisted to DB)
    request.session['_new_user_creds'] = {
        'email': email,
        'username': username,
        'temp_password': temp_password,
        'full_name': f"{first_name} {last_name}".strip(),
    }

    messages.success(request, f"User '{username}' created successfully.")
    return redirect('user_management')


@login_required
def get_temp_creds_view(request):
    """Return and clear one-time temp creds from session (AJAX)."""
    creds = request.session.pop('_new_user_creds', None)
    if creds:
        return JsonResponse({'ok': True, 'creds': creds})
    return JsonResponse({'ok': False})


@login_required
@require_POST
def toggle_user_status_view(request, user_id):
    """Activate / deactivate a user within the admin's org."""
    if not _staff_required(request):
        messages.error(request, "Permission denied.")
        return redirect('user_management')

    org = request.user.organization
    target = get_object_or_404(User, pk=user_id, organization=org)

    # Prevent self-deactivation
    if target.pk == request.user.pk:
        messages.error(request, "You cannot deactivate your own account.")
        return redirect('user_management')

    target.is_active   = not target.is_active
    target.is_approved = target.is_active
    target.save()

    status_label = "activated" if target.is_active else "deactivated"
    messages.success(request, f"User '{target.username}' has been {status_label}.")
    return redirect('user_management')


@login_required
@require_POST
def reset_user_password_view(request, user_id):
    """Generate a new temporary password for a user and mark must_change_password."""
    if not _staff_required(request):
        return JsonResponse({'ok': False, 'error': 'Permission denied.'}, status=403)

    org = request.user.organization
    target = get_object_or_404(User, pk=user_id, organization=org)

    temp_password = _generate_temp_password()
    target.set_password(temp_password)
    target.must_change_password = True
    target.save()

    return JsonResponse({
        'ok': True,
        'temp_password': temp_password,
        'email': target.email,
        'username': target.username,
    })


@login_required
@require_POST
def edit_user_role_view(request, user_id):
    """Toggle staff/employee role for a user."""
    if not _staff_required(request):
        messages.error(request, "Permission denied.")
        return redirect('user_management')

    org = request.user.organization
    target = get_object_or_404(User, pk=user_id, organization=org)

    if target.pk == request.user.pk:
        messages.error(request, "You cannot change your own role.")
        return redirect('user_management')

    new_role = request.POST.get('role', '')
    if new_role == 'staff':
        target.is_staff = True
    elif new_role == 'employee':
        target.is_staff = False
    target.save()

    messages.success(request, f"Role updated for '{target.username}'.")
    return redirect('user_management')


@login_required
@require_POST
def convert_to_employee_view(request, user_id):
    """Create an Employee record for a User and assign shift."""
    if not _staff_required(request):
        messages.error(request, "Permission denied.")
        return redirect('user_management')

    org = request.user.organization
    target = get_object_or_404(User, pk=user_id, organization=org)

    # Check if already linked
    if _linked_employee(target):
        messages.error(request, f"User '{target.username}' is already linked to an employee.")
        return redirect('user_management')

    dept_id = request.POST.get('department_id')
    desig_id = request.POST.get('designation_id')
    shift_id = request.POST.get('shift_id')

    try:
        dept = Department.objects.get(pk=dept_id, organization=org) if dept_id else None
        desig = Designation.objects.get(pk=desig_id, organization=org) if desig_id else None
        shift = Shift.objects.get(pk=shift_id, organization=org) if shift_id else None
    except (Department.DoesNotExist, Designation.DoesNotExist, Shift.DoesNotExist):
        messages.error(request, "Invalid department, designation, or shift selected.")
        return redirect('user_management')

    # Generate employee ID
    emp_id = f"EMP-{str(uuid.uuid4())[:4].upper()}"

    emp = Employee.objects.create(
        organization=org,
        employee_id=emp_id,
        first_name=target.first_name or target.username,
        last_name=target.last_name or '',
        email=target.email,
        phone_number=target.phone or '',
        department=dept,
        designation=desig,
        created_by=request.user,
    )

    if shift:
        from django.utils import timezone
        ShiftAssignment.objects.create(
            organization=org,
            employee=emp,
            shift=shift,
            effective_from=timezone.now().date(),
            created_by=request.user
        )

    messages.success(request, f"Successfully created employee profile for '{target.username}'.")
    return redirect('user_management')
