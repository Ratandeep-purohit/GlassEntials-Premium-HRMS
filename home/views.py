from django.shortcuts import render , redirect
from django.contrib.auth.decorators import login_required
from accounts.models import CustomUser , Organization
from datetime import datetime 
from employees.models import Employee
from attendance.models import Attendance

@login_required
def home_view(request):
    # Get the organization the current user belongs to
    organization = request.user.organization
    today = datetime.now().date()
    
    try:
        # SaaS Metrics
        active_employees = Employee.objects.filter(organization=organization, is_active=True)[:5]
        user_count = Employee.objects.filter(organization=organization).count()
        today_date = datetime.now().strftime("%A, %B %d, %Y")
        origination_code = organization.unique_code if organization else "GLOBAL"

        # Attendance Summary (Today)
        present_today = Attendance.objects.filter(organization=organization, date=today, clock_in__isnull=False).count()
        
        # Leave Summary
        from leaves.models import LeaveRequest
        pending_leaves = LeaveRequest.objects.filter(organization=organization, status='PENDING').count()
    except Exception as e:
        print(f"Error in dashboard metrics: {e}")
        active_employees = []
        user_count = 0
        today_date = datetime.now().strftime("%A, %B %d, %Y")
        origination_code = organization.unique_code if organization else "INTERNAL"
        present_today = 0
        pending_leaves = 0
    
    # Also fetch recent employees
    recent_employees = Employee.objects.filter(organization=organization, is_deleted=False).order_by('-created_at')[:5]
    
    # Fetch pending approvals
    pending_approvals = CustomUser.objects.filter(organization=organization, is_approved=False, is_active=True).order_by('-date_joined')

    # Find the employee record for the current user
    current_employee = Employee.objects.filter(email=request.user.email, organization=organization, is_active=True, is_deleted=False).first()
    
    # Get today's attendance for this employee
    today_attendance = None
    if current_employee:
        today_attendance = Attendance.objects.filter(employee=current_employee, date=today).first()

    # Check if currently on break
    on_break = False
    if today_attendance:
        from attendance.models import BreakLog
        on_break = BreakLog.objects.filter(attendance=today_attendance, end_time__isnull=True).exists()

    current_hour = datetime.now().hour
    if current_hour < 12:
        greeting = "Good morning"
    elif 12 <= current_hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    # Fetch Upcoming Data for Dashboard Card
    from leaves.models import Holiday, LeaveRequest
    upcoming_leaves = []
    if current_employee:
        upcoming_leaves = LeaveRequest.objects.filter(
            employee=current_employee,
            status='APPROVED',
            start_date__gte=today
        ).order_by('start_date')[:3]
    
    upcoming_holidays = Holiday.objects.filter(
        organization=organization,
        date__gte=today
    ).order_by('date')
    
    filtered_holidays = [h for h in upcoming_holidays if h.date.weekday() != 6][:5] # 6 is Sunday


    context = {
        'user_count': user_count,
        'today_date': today_date,
        'origination_code': origination_code,
        'active_employees': active_employees,
        'recent_employees': recent_employees,
        'present_today': present_today,
        'pending_leaves': pending_leaves,
        'pending_approvals': pending_approvals,
        'today_attendance': today_attendance,
        'on_break': on_break,
        'organization': organization,
        'current_employee': current_employee,
        'greeting': greeting,
        'upcoming_leaves': upcoming_leaves,
        'upcoming_holidays': filtered_holidays,
    }

    return render(request, 'home.html', context)

@login_required
def notifications_view(request):
    from home.models import Notification
    
    # Mark user's notifications as read when they visit this page
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    
    # The 'global_notifications' list is already available in context via the processor
    return render(request, 'notifications.html')

