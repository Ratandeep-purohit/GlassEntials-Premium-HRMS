from django.shortcuts import render , redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.utils import timezone
from accounts.models import CustomUser , Organization
from employees.models import Employee
from attendance.models import Attendance
from announcements.views import visible_announcements_for

@login_required
def home_view(request):
    # Get the organization the current user belongs to
    organization = request.user.organization
    now = timezone.localtime()
    today = now.date()
    
    try:
        # SaaS Metrics
        active_employees = Employee.objects.filter(organization=organization, is_active=True)[:5]
        user_count = Employee.objects.filter(organization=organization).count()
        today_date = now.strftime("%A, %B %d, %Y")
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
        today_date = now.strftime("%A, %B %d, %Y")
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

    current_hour = now.hour
    if current_hour < 12:
        greeting = "Good morning"
    elif 12 <= current_hour < 17:
        greeting = "Good afternoon"
    else:
        greeting = "Good evening"

    # Fetch upcoming data for dashboard cards from live HR data only.
    from leaves.models import Holiday, LeaveRequest
    from payroll.models import EmployeePayslip

    upcoming_leaves = []
    latest_payslip = None
    if current_employee:
        upcoming_leaves = LeaveRequest.objects.filter(
            employee=current_employee,
            status='APPROVED',
            end_date__gte=today
        ).order_by('start_date')[:3]

        latest_payslip = EmployeePayslip.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            employee=current_employee,
            status__in=[
                EmployeePayslip.Status.GENERATED,
                EmployeePayslip.Status.FINALIZED,
                EmployeePayslip.Status.PAID,
            ],
        ).select_related('payroll_run').order_by(
            '-payroll_run__year',
            '-payroll_run__month',
            '-created_at',
        ).first()

    upcoming_holiday_query = Holiday.objects.filter(
        organization=organization,
        calendar__isnull=False,
        is_optional=False,
        date__gte=today,
    ).order_by('date')

    work_location = (getattr(current_employee, "work_location", "") or "").strip()
    if work_location:
        upcoming_holiday_query = upcoming_holiday_query.filter(
            Q(calendar__is_default=True)
            | Q(calendar__branch="")
            | Q(calendar__branch__iexact=work_location)
        )
    else:
        upcoming_holiday_query = upcoming_holiday_query.filter(
            Q(calendar__is_default=True)
            | Q(calendar__branch="")
            | Q(calendar__branch__isnull=True)
        )

    filtered_holidays = list(upcoming_holiday_query[:5])

    # Employee specific metrics
    my_present_days = 0
    my_pending_leaves = 0
    my_approved_leaves = 0
    
    if current_employee:
        first_day_of_month = today.replace(day=1)
        my_present_days = Attendance.objects.filter(
            employee=current_employee, 
            date__gte=first_day_of_month,
            clock_in__isnull=False
        ).count()
        
        my_pending_leaves = LeaveRequest.objects.filter(
            employee=current_employee,
            status='PENDING'
        ).count()
        
        my_approved_leaves = LeaveRequest.objects.filter(
            employee=current_employee,
            status='APPROVED'
        ).count()

    dashboard_announcements = visible_announcements_for(request.user)[:3]

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
        'latest_payslip': latest_payslip,
        'my_present_days': my_present_days,
        'my_pending_leaves': my_pending_leaves,
        'my_approved_leaves': my_approved_leaves,
        'dashboard_announcements': dashboard_announcements,
    }

    return render(request, 'home.html', context)

@login_required
def notifications_view(request):
    from home.models import Notification
    
    # Mark user's notifications as read when they visit this page
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    
    # The 'global_notifications' list is already available in context via the processor
    return render(request, 'notifications.html')

