from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from django.urls import reverse
from django.utils import timezone
from decimal import Decimal, InvalidOperation
from .models import (
    Location, LeaveType, LeavePolicy, LeaveBalance, LeaveRequest, 
    ApprovalWorkflow, LeaveAccrualLog, Holiday, CompOffRequest,
    LeaveApprovalMatrix, LeaveApprovalMatrixStep, HolidayCalendar
)
from employees.models import Employee, Department, Designation
from .services.balance_engine import LeaveBalanceEngine
from .services.calendar_engine import LeaveCalendarEngine
from .services.eligibility_engine import LeaveEligibilityEngine
from .services.employee_policy import EmployeeLeavePolicyPresenter
from .services.holiday_calendar_service import HolidayCalendarService
from .services.policy_workbench import LeavePolicyWorkbenchService
from .services.restriction_engine import LeaveRestrictionEngine
from datetime import datetime, timedelta
from accounts.models import CustomUser


def get_working_days(start_date, end_date, organization):
    """
    Calculates the number of working days between two dates, 
    excluding weekends and organizational holidays.
    """
    days = 0
    curr = start_date
    holidays = HolidayCalendarService.holiday_dates_for_period(
        organization=organization,
        start_date=start_date,
        end_date=end_date,
        include_optional=False,
    )
    
    while curr <= end_date:
        if curr.weekday() < 5 and curr not in holidays: # Monday to Friday
            days += 1
        curr += timedelta(days=1)
    return days


def _require_staff(request):
    if request.user.is_staff:
        return True
    messages.error(request, "Only Admin or HR can access this leave setup page.")
    return False


def _parse_decimal(value, field_name, minimum=Decimal('0.00')):
    try:
        parsed = Decimal(str(value or '0')).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{field_name} must be a valid number.")

    if parsed < minimum:
        raise ValueError(f"{field_name} cannot be less than {minimum}.")

    return parsed


def _user_for_employee(employee, organization):
    if not employee or not employee.email:
        return None
    return CustomUser.objects.filter(email=employee.email, organization=organization).first()


@login_required
def leave_dashboard_view(request):
    employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
    if not employee:
        messages.error(request, "Employee profile not found. Please contact HR.")
        return redirect('home')

    current_year = timezone.now().year
    balances = list(
        LeaveBalance.objects.filter(
            employee=employee,
            year=current_year,
            leave_type__organization=request.user.organization,
            leave_type__is_active=True,
            leave_type__category__isnull=False,
            leave_type__status='ACTIVE',
            leave_type__is_requestable=True,
        ).select_related('leave_type', 'leave_type__category').prefetch_related(
            'leave_type__enterprise_workflows__steps',
        ).order_by('leave_type__name')
    )
    policy_cards = EmployeeLeavePolicyPresenter.build_cards(employee=employee, balances=balances)
    leave_types = [card['leave_type'] for card in policy_cards if card['available'] > 0]
    leave_type_count = LeaveType.objects.filter(
        organization=request.user.organization,
        is_active=True,
        category__isnull=False,
    ).count()

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
            'leave_categories': leave_type_count,
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
        calendar__isnull=False,
        date__gte=timezone.now().date()
    ).order_by('date')
    
    # Filter out Sundays in Python to be safe with weekday logic
    filtered_holidays = [h for h in upcoming_holidays if h.date.weekday() != 6][:5] # 6 is Sunday

    context = {
        'employee': employee,
        'balances': balances,
        'policy_cards': policy_cards,
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
def manage_leave_types_view(request):
    if not _require_staff(request):
        return redirect('leaves:dashboard')

    organization = request.user.organization

    if request.method == 'POST':
        try:
            leave_type, created = LeavePolicyWorkbenchService.save_from_post(
                organization=organization,
                user=request.user,
                data=request.POST,
                request=request,
            )

            action = "updated" if not created else "created"
            messages.success(request, f"{leave_type.name} policy {action} successfully.")
            return redirect('leaves:create_leave')
        except ValueError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"Could not save leave policy: {exc}")

    leave_types = LeaveType.objects.filter(
        organization=organization,
        is_active=True,
        category__isnull=False,
    ).prefetch_related('policies').order_by('name')

    return render(request, 'leaves/manage_leave_types.html', {
        'leave_types': leave_types,
        'departments': Department.objects.filter(organization=organization, is_active=True, is_deleted=False).order_by('name'),
        'designations': Designation.objects.filter(organization=organization, is_active=True, is_deleted=False).order_by('name'),
    })


@login_required
def assign_leave_balances_view(request):
    if not _require_staff(request):
        return redirect('leaves:dashboard')

    organization = request.user.organization
    current_year = timezone.now().year
    selected_employee_id = request.POST.get('employee') if request.method == 'POST' else request.GET.get('employee', '')
    try:
        selected_year = int((request.POST.get('year') if request.method == 'POST' else request.GET.get('year')) or current_year)
    except (TypeError, ValueError):
        selected_year = current_year

    employees = Employee.objects.filter(
        organization=organization,
        is_active=True,
        is_deleted=False
    ).order_by('first_name', 'last_name', 'employee_id')
    selected_employee = employees.filter(id=selected_employee_id).first() if selected_employee_id else None
    leave_types = LeaveType.objects.filter(
        organization=organization,
        is_active=True,
        category__isnull=False,
        status='ACTIVE',
        is_requestable=True,
    ).select_related('category').prefetch_related('policies').order_by('name')

    for leave_type in leave_types:
        policy = next(iter(leave_type.policies.all()), None)
        leave_type.assignment_default = (
            Decimal(str(policy.max_balance)).quantize(Decimal('0.01'))
            if policy else Decimal('0.00')
        )

    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        selected_leave_ids = request.POST.getlist('leave_types')
        assignment_mode = request.POST.get('assignment_mode', 'SET')

        try:
            year = int(request.POST.get('year') or selected_year)
            if year < 2000 or year > 2100:
                raise ValueError("Enter a valid leave year.")

            if assignment_mode not in ['SET', 'ADD']:
                raise ValueError("Select a valid assignment mode.")

            if not employee_id:
                raise ValueError("Select an employee first.")

            if not selected_leave_ids:
                raise ValueError("Select at least one leave policy to assign.")

            employee = Employee.objects.get(
                id=employee_id,
                organization=organization,
                is_active=True,
                is_deleted=False,
            )

            selected_leave_types = list(LeaveType.objects.filter(
                id__in=selected_leave_ids,
                organization=organization,
                is_active=True,
                category__isnull=False,
                status='ACTIVE',
                is_requestable=True,
            ).order_by('name'))
            if len(selected_leave_types) != len(set(selected_leave_ids)):
                raise ValueError("One or more selected leave policies are not available.")

            updated_count = 0
            for leave_type in selected_leave_types:
                amount = _parse_decimal(
                    request.POST.get(f'amount_{leave_type.id}'),
                    f"{leave_type.name} leave days",
                    minimum=Decimal('0.01'),
                )
                if assignment_mode == 'ADD':
                    LeaveBalanceEngine.adjust(
                        employee=employee,
                        leave_type=leave_type,
                        year=year,
                        amount=amount,
                        organization=organization,
                        user=request.user,
                        source="ADMIN",
                        description=f"Admin added {amount} {leave_type.code} days for {year}.",
                    )
                else:
                    LeaveBalanceEngine.set_balance(
                        employee=employee,
                        leave_type=leave_type,
                        year=year,
                        amount=amount,
                        organization=organization,
                        user=request.user,
                        source="ADMIN",
                        description=f"Admin assigned {amount} {leave_type.code} days for {year}.",
                    )
                updated_count += 1

            messages.success(request, f"{updated_count} leave balance(s) assigned to {employee.first_name} {employee.last_name}.")
            return redirect(f"{reverse('leaves:assign_leaves')}?employee={employee.id}&year={year}")
        except (Employee.DoesNotExist, LeaveType.DoesNotExist):
            messages.error(request, "Selected employee or leave type was not found.")
        except ValueError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"Could not assign leave balance: {exc}")

    recent_balances = LeaveBalance.objects.filter(
        employee__organization=organization,
        year=selected_year,
        leave_type__organization=organization,
        leave_type__category__isnull=False,
    ).select_related('employee', 'leave_type').order_by('employee__first_name', 'leave_type__name')
    if selected_employee:
        recent_balances = recent_balances.filter(employee=selected_employee)

    balance_lookup = {}
    existing_balances = LeaveBalance.objects.filter(
        employee__organization=organization,
        employee__in=employees,
        leave_type__in=leave_types,
        year=selected_year,
    ).select_related('employee', 'leave_type')
    for balance in existing_balances:
        balance_lookup.setdefault(str(balance.employee_id), {})[str(balance.leave_type_id)] = {
            'current': str(Decimal(str(balance.current_balance or 0)).quantize(Decimal('0.01'))),
            'used': str(Decimal(str(balance.used_balance or 0)).quantize(Decimal('0.01'))),
            'pending': str(Decimal(str(balance.pending_balance or 0)).quantize(Decimal('0.01'))),
        }

    return render(request, 'leaves/assign_leave_balances.html', {
        'employees': employees,
        'leave_types': leave_types,
        'recent_balances': recent_balances,
        'current_year': current_year,
        'selected_year': selected_year,
        'selected_employee_id': str(selected_employee_id or ''),
        'selected_employee': selected_employee,
        'balance_lookup': balance_lookup,
    })




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
            leave_type = LeaveType.objects.get(
                id=leave_type_id,
                organization=request.user.organization,
                category__isnull=False,
                status='ACTIVE',
                is_requestable=True,
            )
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

            eligibility = LeaveEligibilityEngine.evaluate(
                employee=employee,
                leave_type=leave_type,
                on_date=start_date,
            )
            if not eligibility['eligible']:
                messages.error(request, " ".join(eligibility['errors']))
                return redirect('leaves:dashboard')

            if start_date > end_date:
                messages.error(request, "Start date cannot be after end date.")
                return redirect('leaves:dashboard')

            # Half-Day Validation
            if session in ['MORNING', 'AFTERNOON'] and start_date != end_date:
                messages.error(request, "Half-day leaves must be for a single day (Start and End date must be the same).")
                return redirect('leaves:dashboard')

            total_days = LeaveCalendarEngine.calculate_days(
                organization=request.user.organization,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                session_type=session,
                employee=employee,
            )

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

            requested_days = Decimal(str(total_days)).quantize(Decimal('0.01'))

            restriction_result = LeaveRestrictionEngine.validate_application(
                employee=employee,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                session_type=session,
                total_days=requested_days,
                attachment=attachment,
            )
            if not restriction_result['valid']:
                messages.error(request, " ".join(restriction_result['errors']))
                return redirect('leaves:dashboard')

            # Check balance

            balance = LeaveBalance.objects.filter(
                employee=employee, 
                leave_type=leave_type, 
                year=start_date.year
            ).first()

            available_balance = (balance.current_balance - balance.pending_balance) if balance else Decimal('0.00')
            negative_limit = Decimal(str(leave_type.negative_balance_limit or 0)).quantize(Decimal('0.01'))
            allowed_available = available_balance + negative_limit if leave_type.allow_negative_balance else available_balance
            if not balance or allowed_available < requested_days:
                messages.error(request, f"Insufficient {leave_type.code} balance.")
                return redirect('leaves:dashboard')

            payable_days = requested_days if leave_type.is_paid else Decimal('0.00')
            lop_days = Decimal('0.00') if leave_type.is_paid else requested_days

            # Create request
            leave_req = LeaveRequest.objects.create(
                employee=employee,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                session_type=session,
                reason=reason,
                attachment=attachment,
                total_days=requested_days,
                payable_days=payable_days,
                lop_days=lop_days,
                policy_version=leave_type.policy_version,
                applied_at=timezone.now(),
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
                        approver = _user_for_employee(employee.manager, request.user.organization)
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
                        approver=_user_for_employee(employee.manager, request.user.organization),
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

            LeaveBalanceEngine.reserve(leave_request=leave_req, user=request.user)

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
                
                LeaveBalanceEngine.consume(leave_request=leave_req, user=request.user)

                
        elif action == 'reject':
            leave_req.status = 'REJECTED'
            leave_req.current_handler = None

            LeaveBalanceEngine.release(
                leave_request=leave_req,
                user=request.user,
                description="Released reserved balance after rejection.",
            )
            
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
def manage_holiday_calendars_view(request):
    if not _require_staff(request):
        return redirect('leaves:dashboard')

    organization = request.user.organization
    current_year = timezone.now().year

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'create_calendar':
                calendar_obj = HolidayCalendarService.create_calendar(
                    organization=organization,
                    user=request.user,
                    name=request.POST.get('name'),
                    year=request.POST.get('year'),
                    branch=request.POST.get('branch'),
                    location_id=request.POST.get('location'),
                    is_default=bool(request.POST.get('is_default')),
                )
                messages.success(request, f"{calendar_obj.name} created successfully.")
                return redirect(f"{reverse('leaves:holiday_calendars')}?year={calendar_obj.year}&calendar={calendar_obj.id}")

            if action == 'copy_calendar':
                calendar_obj, copied_count = HolidayCalendarService.copy_calendar(
                    organization=organization,
                    user=request.user,
                    source_calendar_id=request.POST.get('source_calendar'),
                    target_year=request.POST.get('target_year'),
                    target_name=request.POST.get('target_name'),
                    make_default=bool(request.POST.get('make_default')),
                )
                messages.success(request, f"Copied {copied_count} holiday(s) into {calendar_obj.name}.")
                return redirect(f"{reverse('leaves:holiday_calendars')}?year={calendar_obj.year}&calendar={calendar_obj.id}")

            if action == 'import_holidays':
                calendar_id = request.POST.get('calendar')
                imported_count = HolidayCalendarService.import_csv(
                    organization=organization,
                    user=request.user,
                    calendar_id=calendar_id,
                    uploaded_file=request.FILES.get('csv_file'),
                )
                calendar_obj = HolidayCalendar.objects.get(id=calendar_id, organization=organization)
                messages.success(request, f"Imported {imported_count} holiday(s).")
                return redirect(f"{reverse('leaves:holiday_calendars')}?year={calendar_obj.year}&calendar={calendar_obj.id}")

            if action == 'save_holiday':
                holiday, created = HolidayCalendarService.save_holiday(
                    organization=organization,
                    user=request.user,
                    calendar_id=request.POST.get('calendar'),
                    holiday_id=request.POST.get('holiday_id') or None,
                    name=request.POST.get('holiday_name'),
                    holiday_date=request.POST.get('holiday_date'),
                    holiday_type=request.POST.get('holiday_type'),
                    is_paid=bool(request.POST.get('is_paid')),
                    is_optional=bool(request.POST.get('is_optional')),
                    location_id=request.POST.get('holiday_location'),
                )
                action_label = "created" if created else "updated"
                messages.success(request, f"{holiday.name} {action_label} successfully.")
                return redirect(f"{reverse('leaves:holiday_calendars')}?year={holiday.calendar.year}&calendar={holiday.calendar_id}")

            if action == 'delete_holiday':
                holiday = Holiday.objects.get(id=request.POST.get('holiday_id'), organization=organization)
                calendar_id = holiday.calendar_id
                year = holiday.date.year
                name = holiday.name
                holiday.delete()
                messages.success(request, f"{name} deleted successfully.")
                return redirect(f"{reverse('leaves:holiday_calendars')}?year={year}&calendar={calendar_id}")

            if action == 'set_default':
                calendar_obj = HolidayCalendar.objects.get(id=request.POST.get('calendar'), organization=organization)
                HolidayCalendar.objects.filter(
                    organization=organization,
                    year=calendar_obj.year,
                    is_default=True,
                ).update(is_default=False)
                calendar_obj.is_default = True
                calendar_obj.updated_by = request.user
                calendar_obj.save(update_fields=['is_default', 'updated_by', 'updated_at'])
                messages.success(request, f"{calendar_obj.name} is now the default calendar for {calendar_obj.year}.")
                return redirect(f"{reverse('leaves:holiday_calendars')}?year={calendar_obj.year}&calendar={calendar_obj.id}")

            messages.error(request, "Select a valid holiday calendar action.")
        except (HolidayCalendar.DoesNotExist, Holiday.DoesNotExist, Location.DoesNotExist):
            messages.error(request, "Selected calendar, holiday, or location was not found.")
        except ValueError as exc:
            messages.error(request, str(exc))
        except Exception as exc:
            messages.error(request, f"Could not update holiday calendar: {exc}")

    try:
        selected_year = int(request.GET.get('year') or current_year)
    except (TypeError, ValueError):
        selected_year = current_year

    all_calendars = HolidayCalendar.objects.filter(
        organization=organization,
    ).select_related('location_fk').prefetch_related('holidays').order_by('-year', 'name')
    year_calendars = all_calendars.filter(year=selected_year)

    selected_calendar = None
    selected_calendar_id = request.GET.get('calendar')
    if selected_calendar_id:
        selected_calendar = year_calendars.filter(id=selected_calendar_id).first()
    if not selected_calendar:
        selected_calendar = year_calendars.filter(is_default=True).first() or year_calendars.first()

    holidays = Holiday.objects.none()
    if selected_calendar:
        holidays = Holiday.objects.filter(
            organization=organization,
            calendar=selected_calendar,
        ).select_related('location_fk').order_by('date', 'name')

    available_years = sorted(
        set(all_calendars.values_list('year', flat=True)) | {current_year, current_year + 1},
        reverse=True,
    )
    holiday_stats = {
        'total': holidays.count(),
        'public': holidays.filter(is_optional=False).count(),
        'optional': holidays.filter(is_optional=True).count(),
        'paid': holidays.filter(is_paid=True).count(),
    }

    return render(request, 'leaves/manage_holiday_calendars.html', {
        'available_years': available_years,
        'selected_year': selected_year,
        'all_calendars': all_calendars,
        'year_calendars': year_calendars,
        'selected_calendar': selected_calendar,
        'holidays': holidays,
        'locations': Location.objects.filter(organization=organization, is_active=True, is_deleted=False).order_by('name'),
        'holiday_stats': holiday_stats,
        'current_year': current_year,
    })


@login_required
def global_calendar_view(request):
    try:
        selected_year = int(request.GET.get('year') or timezone.now().year)
    except (TypeError, ValueError):
        selected_year = timezone.now().year

    year_start = datetime(selected_year, 1, 1).date()
    year_end = datetime(selected_year, 12, 31).date()

    holidays = Holiday.objects.filter(
        organization=request.user.organization,
        calendar__isnull=False,
        date__year=selected_year,
    ).select_related('calendar').order_by('date', 'name')
    leaves = LeaveRequest.objects.filter(
        organization=request.user.organization,
        status='APPROVED',
        start_date__lte=year_end,
        end_date__gte=year_start,
    )
    calendars = HolidayCalendar.objects.filter(
        organization=request.user.organization,
        year=selected_year,
    ).order_by('name')
    available_years = sorted(
        set(HolidayCalendar.objects.filter(
            organization=request.user.organization,
        ).values_list('year', flat=True)) | {timezone.now().year, timezone.now().year + 1},
        reverse=True,
    )
    return render(request, 'leaves/calendar.html', {
        'holidays': holidays,
        'leaves': leaves,
        'calendars': calendars,
        'selected_year': selected_year,
        'available_years': available_years,
    })


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
                current_handler=_user_for_employee(employee.manager, request.user.organization)
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
            leave_req.current_handler = _user_for_employee(leave_req.employee.manager, request.user.organization)
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
            # It's deducted only when it reaches APPROVED state (i.e. all steps are approved)
            if leave_req.status == 'CANCEL_REQUESTED':
                
                # A leave request was fully approved (and balance deducted) ONLY if there are no pending or rejected steps left.
                was_fully_approved = not leave_req.workflow_steps.filter(status__in=['PENDING', 'REJECTED']).exists()
                
                leave_req.status = 'CANCELLED'
                
                if was_fully_approved:
                    balance = LeaveBalance.objects.filter(
                        employee=leave_req.employee,
                        leave_type=leave_req.leave_type,
                        year=leave_req.start_date.year
                    ).first()
                    if balance:
                        balance.used_balance = max(Decimal('0.00'), balance.used_balance - leave_req.total_days)
                        balance.save(update_fields=['used_balance'])
                    LeaveBalanceEngine.adjust(
                        employee=leave_req.employee,
                        leave_type=leave_req.leave_type,
                        year=leave_req.start_date.year,
                        amount=leave_req.total_days,
                        organization=request.user.organization,
                        user=request.user,
                        source="SYSTEM",
                        description=f"Balance credited back for cancelled leave ({leave_req.start_date})",
                    )
                else:
                    LeaveBalanceEngine.release(
                        leave_request=leave_req,
                        user=request.user,
                        description="Released reserved balance after cancellation approval.",
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

    # Show only optional holidays created inside an HR-managed holiday calendar.
    optional_holidays = Holiday.objects.filter(
        organization=request.user.organization,
        calendar__isnull=False,
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
        'remaining': rh_limit - claims.count(),
        'current_year': current_year,
    }
    return render(request, 'leaves/rh_picker.html', context)

@login_required
def claim_rh_view(request, holiday_id):
    """
    Processes the claim or cancellation of a restricted holiday.
    """
    if request.method == 'POST':
        employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
        holiday = get_object_or_404(
            Holiday,
            id=holiday_id,
            organization=request.user.organization,
            calendar__isnull=False,
            is_optional=True,
        )
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
