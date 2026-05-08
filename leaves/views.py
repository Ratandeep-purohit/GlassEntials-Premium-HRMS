from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.utils import timezone
from .models import Location, LeaveType, LeavePolicy, LeaveBalance, LeaveRequest, ApprovalWorkflow, LeaveAccrualLog, Holiday, CompOffRequest
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
                current_handler=employee.manager.user if employee.manager else None,
                start_time=request.POST.get('start_time') if session == 'SHORT' else None,
                end_time=request.POST.get('end_time') if session == 'SHORT' else None
            )


            # Log initial action in the workflow
            ApprovalWorkflow.objects.create(
                leave_request=leave_req,
                approver=request.user,
                sequence_order=1,
                status='APPROVED', # The applicant "approves" their own submission phase
                action_date=timezone.now(),
                comments="Leave application submitted."
            )

            # Create Notification for Staff/HR
            from home.models import Notification
            staff_users = CustomUser.objects.filter(organization=request.user.organization, is_staff=True)
            for staff in staff_users:
                Notification.objects.create(
                    user=staff,
                    organization=request.user.organization,
                    title=f"New Leave: {employee.first_name} {employee.last_name}",
                    message=f"Applied for {leave_type.name} from {start_date} ({total_days} days).",
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
        
    return render(request, 'leaves/pending_approvals.html', {
        'pending_leaves': pending_leaves,
        'pending_compoffs': pending_compoffs,
        'cancel_requests': cancel_requests
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
            if leave_req.status == 'PENDING':
                # If manager approved, move to next level or fully approve if no next level
                # For now, let's say Manager -> HR. 
                # If the user is a manager, move to MANAGER_APPROVED.
                # If the user is HR/Staff, move to APPROVED.
                if request.user.is_staff:
                    leave_req.status = 'APPROVED'
                    # Deduct from balance
                    balance = LeaveBalance.objects.get(
                        employee=leave_req.employee, 
                        leave_type=leave_req.leave_type, 
                        year=leave_req.start_date.year
                    )
                    balance.current_balance -= leave_req.total_days
                    balance.used_balance += leave_req.total_days
                    balance.save()
                else:
                    leave_req.status = 'MANAGER_APPROVED'
                    # Route to HR (for now, any staff)
                    # In a real system, we'd find the specific HR person
                    leave_req.current_handler = None # Placeholder for next level
            elif leave_req.status == 'MANAGER_APPROVED' and request.user.is_staff:
                leave_req.status = 'APPROVED'
                # Deduct balance
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
