from django.shortcuts import render , redirect
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from datetime import timedelta
from accounts.models import CustomUser , Organization
from employees.models import Employee
from attendance.models import Attendance
from announcements.views import visible_announcements_for


def _dashboard_approval_items(organization):
    items = []

    def add_item(*, title, meta, badge, link, timestamp, tone="blue", approve_url=None, reject_url=None):
        items.append({
            "title": title,
            "meta": meta,
            "badge": badge,
            "link": link,
            "timestamp": timestamp,
            "tone": tone,
            "approve_url": approve_url,
            "reject_url": reject_url,
        })

    pending_users = CustomUser.objects.filter(
        organization=organization,
        is_approved=False,
        is_active=True,
    ).order_by("-date_joined")
    for user in pending_users:
        add_item(
            title=f"{user.username}",
            meta=f"{user.email} requested account access",
            badge="Login",
            link=reverse("approve_employee", args=[user.id]),
            approve_url=reverse("approve_employee", args=[user.id]),
            reject_url=reverse("reject_employee", args=[user.id]),
            timestamp=user.date_joined,
            tone="red",
        )

    from attendance.models import AttendanceCorrection, OvertimeRequest
    from leaves.models import CompOffRequest, LeaveRequest
    from payroll.models import DeclarationProof, EmployeeLoan

    pending_leaves = LeaveRequest.objects.filter(
        organization=organization,
        status__in=["PENDING", "MANAGER_APPROVED", "CANCEL_REQUESTED"],
    ).select_related("employee", "leave_type").order_by("-created_at")
    for leave in pending_leaves:
        if leave.status == "CANCEL_REQUESTED":
            badge = "Leave Cancel"
            meta = f"{leave.employee.first_name} requested cancellation for {leave.leave_type.name}"
        else:
            badge = "Leave"
            meta = f"{leave.employee.first_name} requested {leave.total_days} day(s) of {leave.leave_type.name}"
        add_item(
            title=f"{leave.employee.first_name} {leave.employee.last_name}",
            meta=meta,
            badge=badge,
            link=reverse("leaves:pending_approvals"),
            timestamp=leave.created_at,
            tone="blue",
        )

    pending_compoffs = CompOffRequest.objects.filter(
        organization=organization,
        status="PENDING",
    ).select_related("employee").order_by("-created_at")
    for compoff in pending_compoffs:
        add_item(
            title=f"{compoff.employee.first_name} {compoff.employee.last_name}",
            meta=f"Comp-off credit for {compoff.worked_date:%d %b %Y}",
            badge="Comp Off",
            link=reverse("leaves:pending_approvals"),
            timestamp=compoff.created_at,
            tone="purple",
        )

    pending_corrections = AttendanceCorrection.objects.filter(
        employee__organization=organization,
        status="PENDING",
    ).select_related("employee", "attendance").order_by("-created_at")
    for correction in pending_corrections:
        add_item(
            title=f"{correction.employee.first_name} {correction.employee.last_name}",
            meta=f"Attendance correction for {correction.attendance.date:%d %b %Y}",
            badge="Attendance",
            link=reverse("manage_corrections"),
            timestamp=correction.created_at,
            tone="amber",
        )

    pending_overtimes = OvertimeRequest.objects.filter(
        employee__organization=organization,
        status="PENDING",
    ).select_related("employee").order_by("-created_at")
    for overtime in pending_overtimes:
        add_item(
            title=f"{overtime.employee.first_name} {overtime.employee.last_name}",
            meta=f"Requested {overtime.hours_requested} overtime hour(s)",
            badge="Overtime",
            link=reverse("overtime_dashboard"),
            timestamp=overtime.created_at,
            tone="cyan",
        )

    pending_loans = EmployeeLoan.objects.filter(
        organization=organization,
        status=EmployeeLoan.LoanStatus.PENDING_APPROVAL,
    ).select_related("employee").order_by("-created_at")
    for loan in pending_loans:
        add_item(
            title=f"{loan.employee.first_name} {loan.employee.last_name}",
            meta=f"{loan.get_loan_type_display()} loan request for Rs. {loan.principal_amount}",
            badge="Loan",
            link=reverse("admin_loans"),
            timestamp=loan.created_at,
            tone="green",
        )

    pending_proofs = DeclarationProof.objects.filter(
        declaration__tax_profile__employee__organization=organization,
        verification_status=DeclarationProof.VerificationStatus.PENDING,
    ).select_related(
        "declaration__tax_profile__employee",
        "declaration__category",
    ).order_by("-created_at")
    for proof in pending_proofs:
        employee = proof.declaration.tax_profile.employee
        add_item(
            title=f"{employee.first_name} {employee.last_name}",
            meta=f"Tax proof pending for {proof.declaration.category.name}",
            badge="Tax Proof",
            link=reverse("admin_tax_review"),
            timestamp=proof.created_at,
            tone="slate",
        )

    items.sort(key=lambda item: item["timestamp"] or timezone.now(), reverse=True)
    return items, len(items)

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
    
    # Fetch HR/Admin action inbox across employee request modules.
    pending_approval_items = []
    pending_approval_total = 0
    if request.user.is_staff:
        pending_approval_items, pending_approval_total = _dashboard_approval_items(organization)

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

    on_leave_today_query = LeaveRequest.objects.filter(
        organization=organization,
        employee__is_active=True,
        employee__is_deleted=False,
        status='APPROVED',
        start_date__lte=today,
        end_date__gte=today,
    ).select_related(
        'employee',
        'employee__department',
        'employee__designation',
        'leave_type',
    ).order_by('employee__first_name', 'employee__last_name')
    on_leave_today_total = on_leave_today_query.count()
    on_leave_today = list(on_leave_today_query)

    # Employee specific metrics
    my_present_days = 0
    my_pending_leaves = 0
    my_approved_leaves = 0
    last_5_attendance = []
    
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

        recent_dates = [today - timedelta(days=offset) for offset in range(5)]
        recent_attendance = Attendance.objects.filter(
            employee=current_employee,
            date__range=(recent_dates[-1], today),
        )
        recent_attendance_map = {attendance.date: attendance for attendance in recent_attendance}

        for attendance_date in recent_dates:
            attendance = recent_attendance_map.get(attendance_date)
            if attendance and attendance.clock_in and attendance.clock_out:
                status_label = "Completed"
                status_type = "completed"
            elif attendance and attendance.clock_in and attendance_date == today:
                status_label = "Working"
                status_type = "working"
            elif attendance and attendance.clock_in:
                status_label = "Missed Out"
                status_type = "missing"
            elif attendance_date == today:
                status_label = "Not Marked"
                status_type = "pending"
            elif attendance_date.weekday() == 6:  # Sunday only
                status_label = "Weekly Off"
                status_type = "weekend"
            else:
                status_label = "Absent"
                status_type = "absent"

            last_5_attendance.append({
                "date": attendance_date,
                "attendance": attendance,
                "clock_in": attendance.clock_in if attendance else None,
                "clock_out": attendance.clock_out if attendance else None,
                "work_time": attendance.current_work_time if attendance else "--",
                "status_label": status_label,
                "status_type": status_type,
            })

    dashboard_announcements = visible_announcements_for(request.user)[:3]

    context = {
        'user_count': user_count,
        'today_date': today_date,
        'origination_code': origination_code,
        'active_employees': active_employees,
        'recent_employees': recent_employees,
        'present_today': present_today,
        'pending_leaves': pending_leaves,
        'pending_approval_items': pending_approval_items,
        'pending_approval_total': pending_approval_total,
        'today_attendance': today_attendance,
        'on_break': on_break,
        'organization': organization,
        'current_employee': current_employee,
        'greeting': greeting,
        'upcoming_leaves': upcoming_leaves,
        'upcoming_holidays': filtered_holidays,
        'on_leave_today': on_leave_today,
        'on_leave_today_total': on_leave_today_total,
        'latest_payslip': latest_payslip,
        'my_present_days': my_present_days,
        'my_pending_leaves': my_pending_leaves,
        'my_approved_leaves': my_approved_leaves,
        'last_5_attendance': last_5_attendance,
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

