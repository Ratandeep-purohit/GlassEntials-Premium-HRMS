from django.shortcuts import render , redirect
from django.contrib.auth.decorators import login_required
from accounts.models import CustomUser , Organization
from datetime import datetime 
from employees.models import Employee

@login_required
def home_view(request):
    try:
        # Get the organization the current user belongs to
        organization = request.user.organization
        # SaaS Metrics
        active_employees = Employee.objects.filter(organization=organization, is_active=True)[:5]
        user_count = Employee.all_objects.all().count()
        today_date = datetime.now().strftime("%A, %B %d, %Y")
        origination_code = organization.unique_code if organization else "GLOBAL"

        # Attendance Summary (Today)
        from attendance.models import Attendance
        today = datetime.now().date()
        present_today = Attendance.objects.filter(organization=organization, date=today, status__is_attendance_counted=True).count()
        
        # Leave Summary
        from leaves.models import LeaveRequest
        pending_leaves = LeaveRequest.objects.filter(organization=organization, status='PENDING').count()
        
    except Exception as e:
        # Fallback for users without an organization or other errors
        active_employees = Employee.objects.filter(is_active=True)[:5]
        user_count = Employee.objects.all().count()
        today_date = datetime.now().strftime("%A, %B %d, %Y")
        origination_code = "INTERNAL"
        present_today = 0
        pending_leaves = 0
    
    # Also fetch recent employees
    recent_employees = Employee.objects.filter(is_deleted=False).order_by('-created_at')[:5]

    context = {
        'user_count': user_count,
        'today_date': today_date,
        'origination_code': origination_code,
        'active_employees': active_employees,
        'recent_employees': recent_employees,
        'present_today': present_today,
        'pending_leaves': pending_leaves,
    }
    return render(request, 'home.html', context)

# Create your views here.
