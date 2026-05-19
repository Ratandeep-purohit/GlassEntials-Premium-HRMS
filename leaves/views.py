from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from .models import (
    Location, LeaveType, LeavePolicy, LeaveBalance, LeaveRequest, 
    ApprovalWorkflow, LeaveAccrualLog, Holiday, CompOffRequest,
    LeaveApprovalMatrix, LeaveApprovalMatrixStep
)
from employees.models import Employee
from datetime import datetime, timedelta
from accounts.models import CustomUser


def get_working_days(start_date, end_date, organization):
    """
    Calculates the number of working days between two dates, 
    excluding weekends and organizational holidays.
    """
    days = 0
    curr = start_date
    holidays = Holiday.objects.filter(organization=organization).values_list('date', flat=True)
    
    while curr <= end_date:
        if curr.weekday() < 5 and curr not in holidays: # Monday to Friday
            days += 1
        curr += timedelta(days=1)
    return days

@login_required
def leave_dashboard_view(request):
    employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
    if not employee:
        messages.error(request, "Employee profile not found. Please contact HR.")
        return redirect('home')

    current_year = timezone.now().year
    
    # Get or create leave balances for the year
    leave_types = LeaveType.objects.filter(organization=request.user.organization)
    balances = []
    for lt in leave_types:
        # Check if there's a policy for this leave type
        policy = LeavePolicy.objects.filter(leave_type=lt, organization=request.user.organization).first()
        initial_balance = policy.max_balance if policy else 12.0 # Fallback
        
        bal, created = LeaveBalance.objects.get_or_create(
            employee=employee,
            leave_type=lt,
            year=current_year,
            defaults={'current_balance': initial_balance}
        )
        balances.append(bal)

    # Admin Stats
    admin_stats = {}
    team_requests = []
    team_compoffs = []
    if request.user.is_staff:
        admin_stats = {
            'total_pending': LeaveRequest.objects.filter(organization=request.user.organization, status='PENDING').count(),
            'pending_compoffs': CompOffRequest.objects.filter(organization=request.user.organization, status='PENDING').count(),
            'on_leave_today': LeaveRequest.objects.filter(
                organization=request.user.organization, 
                status='APPROVED',
                start_date__lte=timezone.now().date(),
                end_date__gte=timezone.now().date()
            ).count(),
        }
        # Fetch all pending requests for the organization for the admin view
        team_requests = LeaveRequest.objects.filter(
            organization=request.user.organization, 
            status__in=['PENDING', 'MANAGER_APPROVED']
        ).order_by('-created_at')[:5]
        
        team_compoffs = CompOffRequest.objects.filter(
            organization=request.user.organization,
            status='PENDING'
        ).order_by('-created_at')[:5]

    recent_requests = LeaveRequest.objects.filter(employee=employee).order_by('-created_at')[:10]
    recent_compoffs = CompOffRequest.objects.filter(employee=employee).order_by('-created_at')[:10]
    
    # Upcoming Approved Leaves
    upcoming_leaves = LeaveRequest.objects.filter(
        employee=employee,
        status='APPROVED',
        start_date__gte=timezone.now().date()
    ).order_by('start_date')[:3]

    # Upcoming Holidays (Except Sundays)
    upcoming_holidays = Holiday.objects.filter(
        organization=request.user.organization,
        date__gte=timezone.now().date()
    ).order_by('date')
    
    # Filter out Sundays in Python to be safe with weekday logic
    filtered_holidays = [h for h in upcoming_holidays if h.date.weekday() != 6][:5] # 6 is Sunday

    context = {
        'employee': employee,
        'balances': balances,
        'recent_requests': recent_requests,
        'recent_compoffs': recent_compoffs,
        'upcoming_leaves': upcoming_leaves,
        'upcoming_holidays': filtered_holidays,
        'team_requests': team_requests,
        'team_compoffs': team_compoffs,
        'leave_types': leave_types,
        'admin_stats': admin_stats,
    }
    return render(request, 'leaves/leave_dashboard.html', context)




@login_required
def apply_leave_view(request):
    if request.method == 'POST':
        employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
        leave_type_id = request.POST.get('leave_type')
        start_date_str = request.POST.get('start_date')
        end_date_str = request.POST.get('end_date')
        session = request.POST.get('session', 'FULL')
        reason = request.POST.get('reason')
        attachment = request.FILES.get('attachment')

        try:
            leave_type = LeaveType.objects.get(id=leave_type_id, organization=request.user.organization)
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            if start_date > end_date:
                messages.error(request, "Start date cannot be after end date.")
                return redirect('leaves:dashboard')

            # Half-Day Validation
            if session in ['MORNING', 'AFTERNOON'] and start_date != end_date:
                messages.error(request, "Half-day leaves must be for a single day (Start and End date must be the same).")
                return redirect('leaves:dashboard')

            # Calculate days
            if session == 'FULL':
                total_days = get_working_days(start_date, end_date, request.user.organization)
            elif session == 'SHORT':
                total_days = 0.25 # Represents 2 hours out of 8
            else:
                total_days = 0.5

            if total_days <= 0:
                messages.error(request, "Selected range contains no working days.")
                return redirect('leaves:dashboard')

            # Short Leave Monthly Limit Check (SHL code)
            if leave_type.code == 'SHL':
                current_month = start_date.month
                current_year = start_date.year
                existing_shl_count = LeaveRequest.objects.filter(
                    employee=employee,
                    leave_type=leave_type,
                    start_date__month=current_month,
                    start_date__year=current_year,
                    status__in=['PENDING', 'APPROVED', 'MANAGER_APPROVED']
                ).count()
                
                if existing_shl_count >= 2:
                    messages.error(request, "Short Leave limit reached (Maximum 2 per month).")
                    return redirect('leaves:dashboard')
                
                # For Short Leave, we deduct 1.0 from the balance of 2.0 per month
                total_days = 1.0 

            # Check balance

            balance = LeaveBalance.objects.filter(
                employee=employee, 
                leave_type=leave_type, 
                year=start_date.year
            ).first()

            if not balance or balance.current_balance < total_days:
                messages.error(request, f"Insufficient {leave_type.code} balance.")
                return redirect('leaves:dashboard')

            # Create request
            leave_req = LeaveRequest.objects.create(
                employee=employee,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                session_type=session,
                reason=reason,
                attachment=attachment,
                total_days=total_days,
                organization=request.user.organization,
                created_by=request.user,
                start_time=request.POST.get('start_time') if session == 'SHORT' else None,
                end_time=request.POST.get('end_time') if session == 'SHORT' else None
            )

            # Workflow Generation Logic
            matrix = LeaveApprovalMatrix.objects.filter(
                organization=request.user.organization,
                leave_type=leave_type,
                is_active=True
            ).first()

            if not matrix:
                matrix = LeaveApprovalMatrix.objects.filter(
                    organization=request.user.organization,
                    department=employee.department,
                    is_active=True
                ).first()

            if matrix:
                steps = matrix.steps.all().order_by('order')
                for step in steps:
                    # Resolve Approver based on role
                    approver = None
                    if step.approver_role == 'MANAGER':
                        approver = employee.manager.user if employee.manager else None
                    elif step.approver_role == 'HR':
                        approver = CustomUser.objects.filter(organization=request.user.organization, is_staff=True).first()
                    
                    ApprovalWorkflow.objects.create(
                        leave_request=leave_req,
                        approver=approver,
                        approver_role=step.approver_role,
                        sequence_order=step.order,
                        is_parallel=step.is_parallel,
                        status='PENDING',
                        organization=request.user.organization
                    )
            else:
                # Default Fallback: Manager -> HR
                if employee.manager:
                    ApprovalWorkflow.objects.create(
                        leave_request=leave_req,
                        approver=employee.manager.user,
                        approver_role='MANAGER',
                        sequence_order=1,
                        status='PENDING',
                        organization=request.user.organization
                    )
                
                ApprovalWorkflow.objects.create(
                    leave_request=leave_req,
                    approver=None, # Any staff
                    approver_role='HR',
                    sequence_order=2,
                    status='PENDING',
                    organization=request.user.organization
                )

            # Set current handler to the first step approver
            first_step = leave_req.workflow_steps.filter(status='PENDING').first()
            if first_step:
                leave_req.current_handler = first_step.approver
                leave_req.save()

            # Initial Notification for First Approver
            if leave_req.current_handler:
                from home.models import Notification
                Notification.objects.create(
                    user=leave_req.current_handler,
                    organization=request.user.organization,
                    title=f"New Leave: {employee.first_name}",
                    message=f"Awaiting your approval for {leave_type.name}.",
                    notification_type='LEAVE',
                    link='/leaves/pending/'
                )

            messages.success(request, "Leave application submitted successfully.")

        except Exception as e:
            messages.error(request, f"Error: {str(e)}")
        
    return redirect('leaves:dashboard')

@login_required
def leave_history_view(request):
    employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
    requests = LeaveRequest.objects.filter(employee=employee).order_by('-start_date')
    return render(request, 'leaves/leave_history.html', {'requests': requests})

@login_required
def pending_approvals_view(request):
    if request.user.is_staff:
        # Staff can see all pending leaves in the organization
        pending_leaves = LeaveRequest.objects.filter(
            organization=request.user.organization, 
            status__in=['PENDING', 'MANAGER_APPROVED']
        ).order_by('-created_at')
        
        cancel_requests = LeaveRequest.objects.filter(
            organization=request.user.organization,
            status='CANCEL_REQUESTED'
        ).order_by('-created_at')

        pending_compoffs = CompOffRequest.objects.filter(
            organization=request.user.organization,
            status='PENDING'
        ).order_by('-created_at')
    else:
        # Managers only see leaves assigned to them
        pending_leaves = LeaveRequest.objects.filter(
            current_handler=request.user, 
            status__in=['PENDING', 'MANAGER_APPROVED']
        ).order_by('-created_at')
        
        cancel_requests = LeaveRequest.objects.filter(
            current_handler=request.user,
            status='CANCEL_REQUESTED'
        ).order_by('-created_at')

        pending_compoffs = CompOffRequest.objects.filter(
            current_handler=request.user,
            status='PENDING'
        ).order_by('-created_at')
        
    for leave in pending_leaves:
        pending_step = leave.workflow_steps.filter(status='PENDING').first()
        leave.awaiting_role = pending_step.approver_role if pending_step else "Finalized"

    employees_for_export = None
    if request.user.is_staff:
        employees_for_export = Employee.objects.filter(organization=request.user.organization, is_active=True, is_deleted=False).order_by('first_name')

    return render(request, 'leaves/pending_approvals.html', {
        'pending_leaves': pending_leaves,
        'pending_compoffs': pending_compoffs,
        'cancel_requests': cancel_requests,
        'employees_for_export': employees_for_export
    })






@login_required
def approve_reject_action_view(request, leave_id):
    if request.user.is_staff:
        # Staff can approve any leave in the organization
        leave_req = get_object_or_404(LeaveRequest, id=leave_id, organization=request.user.organization)
    else:
        # Managers can only approve leaves assigned to them
        leave_req = get_object_or_404(LeaveRequest, id=leave_id, current_handler=request.user)
    
    if request.method == 'POST':

        action = request.POST.get('action') # 'approve' or 'reject'
        comments = request.POST.get('comments', '')
        
        old_status = leave_req.status
        if action == 'approve':
            # Update the current step in the workflow
            current_step = leave_req.workflow_steps.filter(status='PENDING').first()
            if current_step:
                current_step.status = 'APPROVED'
                current_step.action_date = timezone.now()
                current_step.comments = comments
                current_step.save()

            # Find the next step
            next_step = leave_req.workflow_steps.filter(status='PENDING').order_by('sequence_order').first()
            
            if next_step:
                leave_req.status = 'MANAGER_APPROVED'
                leave_req.current_handler = next_step.approver
                # If next step is HR (Parallel), any staff can approve
                if next_step.approver_role == 'HR' and not next_step.approver:
                    leave_req.current_handler = None # Broad access
            else:
                # No more steps - Fully Approved
                leave_req.status = 'APPROVED'
                leave_req.current_handler = None
                
                # Deduct from balance
                balance = LeaveBalance.objects.get(
                    employee=leave_req.employee, 
                    leave_type=leave_req.leave_type, 
                    year=leave_req.start_date.year
                )
                balance.current_balance -= leave_req.total_days
                balance.used_balance += leave_req.total_days
                balance.save()

                
        elif action == 'reject':
            leave_req.status = 'REJECTED'
            leave_req.current_handler = None
            
        leave_req.save()
        
        # Create Notification for the Employee
        from accounts.models import CustomUser
        from home.models import Notification
        
        # Try to find the user associated with this employee
        target_user = leave_req.created_by
        if not target_user:
            target_user = CustomUser.objects.filter(email=leave_req.employee.email, organization=leave_req.organization).first()
            
        if target_user:
            status_msg = "Approved" if action == 'approve' else "Rejected"
            Notification.objects.create(
                user=target_user,
                organization=leave_req.organization,
                title=f"Leave Request {status_msg}",
                message=f"Your leave request for {leave_req.start_date} has been {status_msg.lower()}.",
                notification_type='LEAVE',
                link='/leaves/history/'
            )
        
        # Log the action in the workflow
        ApprovalWorkflow.objects.create(
            leave_request=leave_req,
            approver=request.user,
            sequence_order=2, # Simplified for now
            status=action.upper() + 'D', # APPROVED or REJECTED
            action_date=timezone.now(),
            comments=comments
        )
        messages.success(request, f"Leave {action}ed successfully.")
        
    return redirect('leaves:pending_approvals')

@login_required
def global_calendar_view(request):
    # This would typically return JSON for a calendar library or render a calendar template
    holidays = Holiday.objects.filter(organization=request.user.organization)
    leaves = LeaveRequest.objects.filter(organization=request.user.organization, status='APPROVED')
    return render(request, 'leaves/calendar.html', {'holidays': holidays, 'leaves': leaves})


@login_required
def apply_compoff_view(request):
    if request.method == 'POST':
        employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
        worked_date_str = request.POST.get('worked_date')
        reason = request.POST.get('reason')

        try:
            worked_date = datetime.strptime(worked_date_str, '%Y-%m-%d').date()
            
            # Basic validation: cannot apply for future dates
            if worked_date > timezone.now().date():
                messages.error(request, "Cannot apply for future dates.")
                return redirect('leaves:dashboard')

            # Create CompOffRequest
            CompOffRequest.objects.create(
                employee=employee,
                worked_date=worked_date,
                reason=reason,
                organization=request.user.organization,
                current_handler=employee.manager.user if employee.manager else None
            )

            # Notification for Manager/HR
            from home.models import Notification
            staff_users = CustomUser.objects.filter(organization=request.user.organization, is_staff=True)
            for staff in staff_users:
                Notification.objects.create(
                    user=staff,
                    organization=request.user.organization,
                    title=f"New Comp-off Request: {employee.first_name}",
                    message=f"Requested credit for working on {worked_date}.",
                    notification_type='LEAVE',
                    link='/leaves/pending/'
                )

            messages.success(request, "Comp-off credit request submitted successfully.")
        except Exception as e:
            messages.error(request, f"Error: {str(e)}")

    return redirect('leaves:dashboard')

@login_required
def compoff_action_view(request, compoff_id):
    if request.user.is_staff:
        compoff_req = get_object_or_404(CompOffRequest, id=compoff_id, organization=request.user.organization)
    else:
        compoff_req = get_object_or_404(CompOffRequest, id=compoff_id, current_handler=request.user)

    if request.method == 'POST':
        action = request.POST.get('action') # 'approve' or 'reject'
        
        if action == 'approve':
            compoff_req.status = 'APPROVED'
            
            # Find the "Comp-off" leave type
            compoff_type = LeaveType.objects.get(code='COMP', organization=request.user.organization)
            
            # Increment balance
            balance, created = LeaveBalance.objects.get_or_create(
                employee=compoff_req.employee,
                leave_type=compoff_type,
                year=compoff_req.worked_date.year,
                defaults={'current_balance': 0.0}
            )
            balance.current_balance += 1.0
            balance.save()

            # Log accrual
            LeaveAccrualLog.objects.create(
                employee=compoff_req.employee,
                leave_type=compoff_type,
                amount=1.0,
                action_type='COMP_OFF_CREDIT',
                description=f"Comp-off credit for working on {compoff_req.worked_date}",
                organization=request.user.organization
            )
        else:
            compoff_req.status = 'REJECTED'

        compoff_req.save()
        messages.success(request, f"Comp-off request {action}ed successfully.")

    return redirect('leaves:pending_approvals')

@login_required
def request_leave_cancellation_view(request, leave_id):
    """
    Employee requests to cancel an already approved or pending leave.
    """
    leave_req = get_object_or_404(LeaveRequest, id=leave_id, employee__email=request.user.email)
    
    if leave_req.status not in ['PENDING', 'APPROVED', 'MANAGER_APPROVED']:
        messages.error(request, "This leave cannot be cancelled.")
        return redirect('leaves:history')
        
    if request.method == 'POST':
        leave_req.status = 'CANCEL_REQUESTED'
        # Route back to manager or HR
        if leave_req.employee.manager:
            leave_req.current_handler = leave_req.employee.manager.user
        leave_req.save()
        
        # Notification for Manager/HR
        from home.models import Notification
        if leave_req.current_handler:
            Notification.objects.create(
                user=leave_req.current_handler,
                organization=request.user.organization,
                title=f"Cancellation Requested: {leave_req.employee.first_name}",
                message=f"Requested to cancel leave for {leave_req.start_date}.",
                notification_type='LEAVE',
                link='/leaves/pending/'
            )
            
        messages.success(request, "Cancellation request submitted.")
    return redirect('leaves:history')

@login_required
def cancel_approval_action_view(request, leave_id):
    """
    Manager/HR approves or rejects the cancellation request.
    """
    if request.user.is_staff:
        leave_req = get_object_or_404(LeaveRequest, id=leave_id, organization=request.user.organization)
    else:
        leave_req = get_object_or_404(LeaveRequest, id=leave_id, current_handler=request.user)

    if request.method == 'POST':
        action = request.POST.get('action') # 'approve' or 'reject'
        comments = request.POST.get('comments', '')
        
        if action == 'approve':
            # Credit back the balance if it was already deducted
            # It's deducted only when it reaches APPROVED state
            if leave_req.status == 'CANCEL_REQUESTED':
                # Important: only credit back if it was previously APPROVED
                # If it was PENDING/MANAGER_APPROVED, it wasn't deducted yet.
                # Actually, in our current logic in approve_reject_action_view, 
                # deduction happens at APPROVED.
                
                # We should check if it was 'APPROVED' before being moved to 'CANCEL_REQUESTED'
                # For simplicity, let's look at the workflow or just check total_days.
                # Since we don't have a 'previous_status' field, we can infer from the status.
                # Actually, let's credit back regardless IF deduction logic is consistent.
                
                # In our system, deduction happens only when status becomes 'APPROVED'.
                # But once it's 'CANCEL_REQUESTED', how do we know if it WAS 'APPROVED'?
                # Usually, cancellation is only for approved leaves. 
                # If a user cancels a PENDING leave, it's just 'REJECTED' or 'CANCELLED' without credit.
                
                # Let's assume for now that if it was approved, we credit.
                # A better way: check if status was APPROVED. 
                # Let's add a log check.
                was_approved = ApprovalWorkflow.objects.filter(leave_request=leave_req, status='APPROVED').exists()
                
                leave_req.status = 'CANCELLED'
                
                if was_approved:
                    balance = LeaveBalance.objects.get(
                        employee=leave_req.employee,
                        leave_type=leave_req.leave_type,
                        year=leave_req.start_date.year
                    )
                    balance.current_balance += leave_req.total_days
                    balance.used_balance -= leave_req.total_days
                    balance.save()
                    
                    # Log credit back
                    LeaveAccrualLog.objects.create(
                        employee=leave_req.employee,
                        leave_type=leave_req.leave_type,
                        amount=leave_req.total_days,
                        action_type='LEAVE_CANCEL_CREDIT',
                        description=f"Balance credited back for cancelled leave ({leave_req.start_date})",
                        organization=request.user.organization
                    )
            
        elif action == 'reject':
            # Revert to previous status? Hard to know. 
            # Let's set it back to APPROVED if it was requested from APPROVED.
            leave_req.status = 'APPROVED'
            
        leave_req.save()
        messages.success(request, f"Cancellation {action}ed.")
        
    return redirect('leaves:pending_approvals')

@login_required
def rh_picker_view(request):
    """
    Displays available optional holidays for the current year.
    """
    employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
    current_year = timezone.now().year
    
    # Get RH Leave Policy for limit
    rh_type = LeaveType.objects.filter(code='RH', organization=request.user.organization).first()
    policy = LeavePolicy.objects.filter(leave_type=rh_type, organization=request.user.organization).first()
    rh_limit = int(policy.max_balance) if policy else 2

    # Get all optional holidays for the year
    optional_holidays = Holiday.objects.filter(
        organization=request.user.organization,
        is_optional=True,
        date__year=current_year
    ).order_by('date')

    # Get employee's claims
    from .models import RestrictedHolidayClaim
    claims = RestrictedHolidayClaim.objects.filter(
        employee=employee,
        year=current_year,
        status__in=['APPROVED', 'PENDING']
    )
    claimed_holiday_ids = list(claims.values_list('holiday_id', flat=True))
    
    context = {
        'optional_holidays': optional_holidays,
        'claimed_holiday_ids': claimed_holiday_ids,
        'rh_limit': rh_limit,
        'claims_count': claims.count(),
        'remaining': rh_limit - claims.count()
    }
    return render(request, 'leaves/rh_picker.html', context)

@login_required
def claim_rh_view(request, holiday_id):
    """
    Processes the claim or cancellation of a restricted holiday.
    """
    if request.method == 'POST':
        employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
        holiday = get_object_or_404(Holiday, id=holiday_id, organization=request.user.organization, is_optional=True)
        current_year = holiday.date.year
        
        # Check if already claimed
        from .models import RestrictedHolidayClaim
        existing_claim = RestrictedHolidayClaim.objects.filter(
            employee=employee,
            holiday=holiday
        ).first()

        if existing_claim:
            # Cancel claim
            existing_claim.delete()
            messages.success(request, f"Cancelled claim for {holiday.name}.")
        else:
            # New claim - check limit
            rh_type = LeaveType.objects.filter(code='RH', organization=request.user.organization).first()
            policy = LeavePolicy.objects.filter(leave_type=rh_type, organization=request.user.organization).first()
            rh_limit = int(policy.max_balance) if policy else 2
            
            current_claims_count = RestrictedHolidayClaim.objects.filter(
                employee=employee,
                year=current_year,
                status__in=['APPROVED', 'PENDING']
            ).count()

            if current_claims_count >= rh_limit:
                messages.error(request, f"You have already reached your limit of {rh_limit} Restricted Holidays.")
            else:
                RestrictedHolidayClaim.objects.create(
                    employee=employee,
                    holiday=holiday,
                    year=current_year,
                    organization=request.user.organization
                )
                messages.success(request, f"Successfully claimed {holiday.name} as a Restricted Holiday.")

    return redirect('leaves:rh_picker')


@login_required
def export_leave_card_view(request):
    if not request.user.is_staff:
        messages.error(request, "Access denied.")
        return redirect('leaves:dashboard')

    employee_id = request.GET.get('employee_id')
    export_format = request.GET.get('format', 'excel')

    if not employee_id:
        messages.error(request, "Please select an employee.")
        return redirect('leaves:pending_approvals')

    employee = get_object_or_404(Employee, id=employee_id, organization=request.user.organization)
    current_year = timezone.now().year

    # Gather data
    balances = LeaveBalance.objects.filter(employee=employee, year=current_year)
    leave_requests = LeaveRequest.objects.filter(employee=employee, status='APPROVED').order_by('-start_date')
    accruals = LeaveAccrualLog.objects.filter(employee=employee).order_by('-created_at')

    import io
    from django.http import HttpResponse

    if export_format == 'excel':
        import xlsxwriter
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)

        # 1. Balances Sheet
        ws_bal = workbook.add_worksheet("Leave Balances")
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#4F46E5', 'font_color': 'white', 'border': 1})
        border_fmt = workbook.add_format({'border': 1})
        title_fmt = workbook.add_format({'bold': True, 'font_size': 14})

        ws_bal.write(0, 0, f"Leave Card for {employee.first_name} {employee.last_name} ({current_year})", title_fmt)
        
        headers_bal = ['Leave Type', 'Current Balance']
        for col, text in enumerate(headers_bal):
            ws_bal.write(2, col, text, header_fmt)

        for row, bal in enumerate(balances, start=3):
            ws_bal.write(row, 0, bal.leave_type.name, border_fmt)
            ws_bal.write(row, 1, float(bal.current_balance), border_fmt)

        ws_bal.set_column(0, 1, 20)

        # 2. Leave History Sheet
        ws_req = workbook.add_worksheet("Leave History")
        headers_req = ['Leave Type', 'Start Date', 'End Date', 'Total Days', 'Reason']
        for col, text in enumerate(headers_req):
            ws_req.write(0, col, text, header_fmt)

        for row, req in enumerate(leave_requests, start=1):
            ws_req.write(row, 0, req.leave_type.name, border_fmt)
            ws_req.write(row, 1, req.start_date.strftime('%Y-%m-%d'), border_fmt)
            ws_req.write(row, 2, req.end_date.strftime('%Y-%m-%d'), border_fmt)
            ws_req.write(row, 3, float(req.total_days), border_fmt)
            ws_req.write(row, 4, req.reason, border_fmt)

        ws_req.set_column(0, 4, 15)

        # 3. Accrual Logs Sheet
        ws_acc = workbook.add_worksheet("Accrual History")
        headers_acc = ['Date', 'Leave Type', 'Action Type', 'Amount', 'Description']
        for col, text in enumerate(headers_acc):
            ws_acc.write(0, col, text, header_fmt)

        for row, log in enumerate(accruals, start=1):
            ws_acc.write(row, 0, log.created_at.strftime('%Y-%m-%d'), border_fmt)
            ws_acc.write(row, 1, log.leave_type.name, border_fmt)
            ws_acc.write(row, 2, log.get_action_type_display(), border_fmt)
            ws_acc.write(row, 3, float(log.amount), border_fmt)
            ws_acc.write(row, 4, log.description, border_fmt)

        ws_acc.set_column(0, 4, 20)

        workbook.close()
        output.seek(0)
        
        response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response['Content-Disposition'] = f'attachment; filename="{employee.first_name}_Leave_Card_{current_year}.xlsx"'
        return response

    elif export_format == 'pdf':
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        elements.append(Paragraph(f"Employee Leave Card: {employee.first_name} {employee.last_name}", styles['Title']))
        elements.append(Paragraph(f"Year: {current_year} | ID: {employee.employee_id}", styles['Normal']))
        elements.append(Spacer(1, 20))

        # Balances
        elements.append(Paragraph("Current Balances", styles['Heading2']))
        data_bal = [['Leave Type', 'Current Balance']]
        for bal in balances:
            data_bal.append([bal.leave_type.name, str(bal.current_balance)])
        
        if len(data_bal) > 1:
            t_bal = Table(data_bal, colWidths=[200, 100])
            t_bal.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(t_bal)
        else:
            elements.append(Paragraph("No balances found.", styles['Normal']))
            
        elements.append(Spacer(1, 20))

        # Leave History
        elements.append(Paragraph("Leave History (Approved)", styles['Heading2']))
        data_req = [['Leave Type', 'Start Date', 'End Date', 'Days']]
        for req in leave_requests[:20]: # Limit to 20 for PDF
            data_req.append([
                req.leave_type.name,
                req.start_date.strftime('%d/%m/%Y'),
                req.end_date.strftime('%d/%m/%Y'),
                str(req.total_days)
            ])
            
        if len(data_req) > 1:
            t_req = Table(data_req, colWidths=[150, 100, 100, 50])
            t_req.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('GRID', (0, 0), (-1, -1), 1, colors.black)
            ]))
            elements.append(t_req)
        else:
            elements.append(Paragraph("No approved leave requests found.", styles['Normal']))

        doc.build(elements)
        output.seek(0)
        response = HttpResponse(output.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{employee.first_name}_Leave_Card_{current_year}.pdf"'
        return response

    return redirect('leaves:pending_approvals')
