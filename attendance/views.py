from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from .models import Shift, ShiftAssignment, AttendanceCorrection
from django.core.exceptions import ValidationError
from employees.models import Employee

from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from datetime import datetime, date, timedelta, time
import calendar
from django.utils import timezone
from .models import Attendance


def _month_bounds(anchor_date):
    month_start = anchor_date.replace(day=1)
    month_end = anchor_date.replace(day=calendar.monthrange(anchor_date.year, anchor_date.month)[1])
    return month_start, month_end


def _attendance_row(employee, row_date, attendance=None, is_staff=False, today=None):
    today = today or timezone.localdate()
    correction = None
    if attendance:
        corrections = list(attendance.corrections.all())
        correction = corrections[0] if corrections else None

    if attendance and attendance.clock_in and attendance.clock_out:
        status_label = "Completed"
        status_type = "completed"
    elif attendance and attendance.clock_in and row_date == today:
        status_label = "Working"
        status_type = "working"
    elif attendance and attendance.clock_in:
        status_label = "Missed Out"
        status_type = "missing"
    elif row_date.weekday() >= 5:
        status_label = "Weekly Off"
        status_type = "weekend"
    else:
        status_label = "Absent"
        status_type = "absent"

    return {
        "employee": employee,
        "date": row_date,
        "attendance": attendance,
        "id": attendance.id if attendance else "",
        "clock_in": attendance.clock_in if attendance else None,
        "clock_out": attendance.clock_out if attendance else None,
        "late_minutes": attendance.late_minutes if attendance else 0,
        "early_out_minutes": attendance.early_out_minutes if attendance else 0,
        "formatted_late_time": attendance.formatted_late_time if attendance else "",
        "formatted_early_out_time": attendance.formatted_early_out_time if attendance else "",
        "current_work_time": attendance.current_work_time if attendance else "--",
        "total_break_minutes": attendance.total_break_minutes if attendance else 0,
        "net_work_hours": attendance.net_work_hours if attendance else None,
        "status_label": status_label,
        "status_type": status_type,
        "correction": correction,
        "can_request_correction": bool(attendance and not is_staff),
    }


def _build_visual_attendance_register(employees, month_start, month_end, attendance_map, organization, today):
    from leaves.models import Holiday, LeaveRequest

    register_dates = [
        month_start + timedelta(days=offset)
        for offset in range((month_end - month_start).days + 1)
    ]

    holiday_qs = Holiday.objects.filter(
        organization=organization,
        date__range=(month_start, month_end),
        is_deleted=False,
    ).select_related('calendar')
    holiday_map = {holiday.date: holiday for holiday in holiday_qs}

    leave_day_map = {}
    if employees:
        leave_qs = LeaveRequest.objects.filter(
            organization=organization,
            employee__in=employees,
            status='APPROVED',
            start_date__lte=month_end,
            end_date__gte=month_start,
            is_deleted=False,
        ).select_related('employee', 'leave_type')

        for leave in leave_qs:
            leave_day = max(leave.start_date, month_start)
            leave_end = min(leave.end_date, month_end)
            is_half_day = (
                leave.session_type in ('MORNING', 'AFTERNOON', 'SHORT')
                or float(leave.total_days or 0) < 1
            )
            while leave_day <= leave_end:
                leave_day_map[(leave.employee_id, leave_day)] = {
                    'class': 'half' if is_half_day else 'leave',
                    'code': 'H' if is_half_day else 'L',
                    'label': 'Half Day' if is_half_day else 'Leave',
                    'title': f"{leave.leave_type.name} ({leave.get_session_type_display()})",
                }
                leave_day += timedelta(days=1)

    counts = {
        'present': 0,
        'leave': 0,
        'half': 0,
        'absent': 0,
        'holiday': 0,
        'weekend': 0,
    }
    rows = []

    for employee in employees:
        cells = []
        for row_date in register_dates:
            attendance = attendance_map.get((employee.id, row_date))
            leave_cell = leave_day_map.get((employee.id, row_date))
            holiday = holiday_map.get(row_date)
            is_weekend = row_date.weekday() >= 5
            title_date = row_date.strftime('%d %b %Y')

            if leave_cell:
                cell = {
                    'date': row_date,
                    'class': leave_cell['class'],
                    'code': leave_cell['code'],
                    'label': leave_cell['label'],
                    'title': f"{title_date}: {leave_cell['title']}",
                    'is_today': row_date == today,
                }
                counts['half' if leave_cell['class'] == 'half' else 'leave'] += 1
            elif attendance and attendance.clock_in:
                cell = {
                    'date': row_date,
                    'class': 'present',
                    'code': 'P',
                    'label': 'Present',
                    'title': f"{title_date}: In {attendance.clock_in.strftime('%I:%M %p')}"
                             f"{' / Out ' + attendance.clock_out.strftime('%I:%M %p') if attendance.clock_out else ''}",
                    'is_today': row_date == today,
                }
                counts['present'] += 1
            elif holiday:
                cell = {
                    'date': row_date,
                    'class': 'holiday',
                    'code': 'OH' if holiday.is_optional else 'HD',
                    'label': 'Optional Holiday' if holiday.is_optional else 'Holiday',
                    'title': f"{title_date}: {holiday.name}",
                    'is_today': row_date == today,
                }
                counts['holiday'] += 1
            elif is_weekend:
                cell = {
                    'date': row_date,
                    'class': 'weekend',
                    'code': 'W',
                    'label': 'Weekly Off',
                    'title': f"{title_date}: Weekly off",
                    'is_today': row_date == today,
                }
                counts['weekend'] += 1
            elif row_date <= today:
                cell = {
                    'date': row_date,
                    'class': 'absent',
                    'code': 'A',
                    'label': 'Absent',
                    'title': f"{title_date}: No attendance marked",
                    'is_today': row_date == today,
                }
                counts['absent'] += 1
            else:
                cell = {
                    'date': row_date,
                    'class': 'future',
                    'code': '-',
                    'label': 'Upcoming',
                    'title': f"{title_date}: Upcoming day",
                    'is_today': False,
                }

            cells.append(cell)

        rows.append({
            'employee': employee,
            'days': cells,
        })

    return {
        'days': [{'date': item, 'is_today': item == today} for item in register_dates],
        'rows': rows,
        'counts': counts,
    }


@login_required
def attendance_view(request):
    current_employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization, is_active=True, is_deleted=False).first()
    
    if not request.user.is_staff and not current_employee:
        messages.error(request, "You do not have permission to view the Attendance Dashboard.")
        return redirect('home')
        
    organization = request.user.organization
    today = timezone.localdate()
    
    # Month filter. The old date parameter is still accepted for bookmarked URLs.
    month_str = request.GET.get('month', '')
    filter_date_str = request.GET.get('date', '')
    view_mode = request.GET.get('view', 'list')
    if view_mode not in ('list', 'visual'):
        view_mode = 'list'
    if month_str:
        try:
            display_date = datetime.strptime(f"{month_str}-01", '%Y-%m-%d').date()
        except ValueError:
            display_date = today
    elif filter_date_str:
        try:
            display_date = datetime.strptime(filter_date_str, '%Y-%m-%d').date()
        except ValueError:
            display_date = today
    else:
        display_date = today

    month_start, month_end = _month_bounds(display_date)
    current_month_start = today.replace(day=1)
    if month_start > today:
        period_end = month_start - timedelta(days=1)
    elif month_start == current_month_start:
        period_end = min(month_end, today)
    else:
        period_end = month_end
    
    employee_qs = Employee.objects.filter(
        organization=organization,
        is_active=True,
        is_deleted=False,
    ).select_related('department').order_by('first_name', 'last_name', 'employee_id')

    search_query = request.GET.get('search', '')
    if search_query and request.user.is_staff:
        employee_qs = employee_qs.filter(
            Q(first_name__icontains=search_query) |
            Q(last_name__icontains=search_query) |
            Q(employee_id__icontains=search_query)
        )
        
    if not request.user.is_staff:
        employee_qs = employee_qs.filter(pk=current_employee.pk)

    employees = list(employee_qs)

    attendance_map = {}
    if employees:
        attendance_qs = Attendance.objects.filter(
            employee__in=employees,
            date__range=(month_start, month_end),
        ).select_related(
            'employee',
            'employee__department',
            'shift',
        ).prefetch_related('corrections')
        attendance_map = {(att.employee_id, att.date): att for att in attendance_qs}

    month_dates = []
    if period_end >= month_start:
        total_days = (period_end - month_start).days + 1
        month_dates = [month_start + timedelta(days=offset) for offset in range(total_days)]

    attendance_rows = []
    for row_date in reversed(month_dates):
        for employee in employees:
            attendance_rows.append(
                _attendance_row(
                    employee,
                    row_date,
                    attendance_map.get((employee.id, row_date)),
                    is_staff=request.user.is_staff,
                    today=today,
                )
            )

    visual_register = _build_visual_attendance_register(
        employees=employees,
        month_start=month_start,
        month_end=month_end,
        attendance_map=attendance_map,
        organization=organization,
        today=today,
    )

    # Stats
    total_employees = Employee.objects.filter(organization=organization, is_active=True, is_deleted=False).count()
    present_count = sum(1 for row in attendance_rows if row["clock_in"])
    late_count = sum(1 for row in attendance_rows if row["late_minutes"] > 0)
    absent_count = sum(1 for row in attendance_rows if row["status_type"] == "absent")
    
    pending_corrections_count = 0
    if request.user.is_staff:
        from .models import AttendanceCorrection
        pending_corrections_count = AttendanceCorrection.objects.filter(employee__organization=organization, status='PENDING').count()
    
    context = {
        'attendances': attendance_rows,
        'total_employees': total_employees,
        'present_count': present_count,
        'absent_count': absent_count,
        'late_count': late_count,
        'display_date': display_date,
        'month_start': month_start,
        'month_end': month_end,
        'period_end': period_end,
        'selected_month_value': month_start.strftime('%Y-%m'),
        'today': today,
        'search_query': search_query,
        'pending_corrections_count': pending_corrections_count,
        'attendance_register_days': visual_register['days'],
        'attendance_register_rows': visual_register['rows'],
        'attendance_register_counts': visual_register['counts'],
        'view_mode': view_mode,
    }
    return render(request, 'attendance_dashboard.html', context)


@login_required
def attendance_visual_view(request):
    params = request.GET.copy()
    params['view'] = 'visual'
    return redirect(f"{reverse('attendance')}?{params.urlencode()}")


def create_shift_view(request,pk=None):
    edit_shift = None
    
    # Handle edit query parameter
    if not pk and request.GET.get('edit'):
        pk = request.GET.get('edit')
        
    if pk:
        try:
            edit_shift = Shift.objects.get(pk=pk, organization=request.user.organization, is_deleted=False)
        except Shift.DoesNotExist:
            messages.error(request, 'Shift not found.')
            return redirect('create_shift')
            
    if request.method == 'POST':
        # Handle delete
        delete_id = request.GET.get('delete')
        if delete_id:
            try:
                shift_to_delete = Shift.objects.get(pk=delete_id, organization=request.user.organization, is_deleted=False)
                shift_to_delete.is_deleted = True
                shift_to_delete.updated_by = request.user
                shift_to_delete.save()
                messages.success(request, f'Shift "{shift_to_delete.name}" deleted successfully.')
            except Shift.DoesNotExist:
                messages.error(request, 'Shift not found.')
            return redirect('create_shift')
            
        name = request.POST.get('name', '').strip()
        start_time = request.POST.get('start_time', '').strip()
        end_time = request.POST.get('end_time', '').strip()
        grace_minutes = request.POST.get('grace_minutes', '').strip()
        minimum_half_day_hours = request.POST.get('minimum_half_day_hours', '').strip()
        minimum_full_day_hours = request.POST.get('minimum_full_day_hours', '').strip()
        is_night_shift = 'is_night_shift' in request.POST
        
        if not name:
            messages.error(request, "Shift name is required.")
            return redirect('create_shift')
        
        if not start_time or not end_time:
            messages.error(request, "Shift time is required.")
            return redirect('create_shift')

        # Check uniqueness across all records (including deleted)
        existing_shift = Shift.objects.filter(organization=request.user.organization, name__iexact=name).first()
        if existing_shift:
            if edit_shift and existing_shift.pk == edit_shift.pk:
                pass # Editing same record
            elif not existing_shift.is_deleted:
                messages.error(request, f'A shift named "{name}" already exists.')
                return redirect('create_shift')
            else:
                # Restore deleted shift
                existing_shift.is_deleted = False
                existing_shift.is_active = True
                existing_shift.grace_minutes = grace_minutes
                existing_shift.minimum_half_day_hours = minimum_half_day_hours
                existing_shift.minimum_full_day_hours = minimum_full_day_hours
                existing_shift.is_night_shift = is_night_shift
                existing_shift.updated_by = request.user
                existing_shift.save()
                messages.success(request, f'Shift "{name}" has been restored.')
                return redirect('create_shift')
        
        if edit_shift:
            edit_shift.name = name
            edit_shift.start_time = start_time
            edit_shift.end_time = end_time
            edit_shift.grace_minutes = grace_minutes
            edit_shift.minimum_half_day_hours = minimum_half_day_hours
            edit_shift.minimum_full_day_hours = minimum_full_day_hours
            edit_shift.is_night_shift = is_night_shift
            edit_shift.updated_by = request.user
            edit_shift.save()
            messages.success(request, f'Shift "{name}" updated successfully!')
        else:
            Shift.objects.create(
                organization=request.user.organization,
                name=name,
                start_time=start_time,
                end_time=end_time,
                grace_minutes=grace_minutes,
                minimum_half_day_hours=minimum_half_day_hours,
                minimum_full_day_hours=minimum_full_day_hours,
                is_night_shift=is_night_shift,
                created_by=request.user
            )
            messages.success(request, f'Shift "{name}" created successfully!')
        return redirect('create_shift')
    
    context = {
        'edit_shift': edit_shift,
        'shifts': Shift.objects.filter(organization=request.user.organization, is_deleted=False).order_by('-created_at'),
    }
    return render(request, 'createshift.html', context)

def assign_shift_view(request, pk=None):
    edit_assignment = None
    
    if not pk and request.GET.get('edit'):
        pk = request.GET.get('edit')
        
    if pk:
        try:
            edit_assignment = ShiftAssignment.objects.get(pk=pk, organization=request.user.organization, is_deleted=False)
        except ShiftAssignment.DoesNotExist:
            messages.error(request, 'Shift assignment not found.')
            return redirect('assign_shift')
            
    if request.method == 'POST':
        # Handle delete
        delete_id = request.GET.get('delete')
        if delete_id:
            try:
                assignment_to_delete = ShiftAssignment.objects.get(pk=delete_id, organization=request.user.organization, is_deleted=False)
                assignment_to_delete.is_deleted = True
                assignment_to_delete.updated_by = request.user
                assignment_to_delete.save()
                messages.success(request, 'Shift assignment deleted successfully.')
            except ShiftAssignment.DoesNotExist:
                messages.error(request, 'Assignment not found.')
            return redirect('assign_shift')
            
        employee_id = request.POST.get('employee_id')
        shift_id = request.POST.get('shift_id')
        effective_from = request.POST.get('effective_from')
        effective_to = request.POST.get('effective_to') or None

        if not employee_id or not shift_id or not effective_from:
            messages.error(request, "Employee, Shift, and Effective From date are required.")
            return redirect('assign_shift')

        try:
            employee = Employee.objects.get(pk=employee_id, organization=request.user.organization, is_deleted=False)
            shift = Shift.objects.get(pk=shift_id, organization=request.user.organization, is_deleted=False)
            
            if edit_assignment:
                edit_assignment.employee = employee
                edit_assignment.shift = shift
                edit_assignment.effective_from = effective_from
                edit_assignment.effective_to = effective_to
                edit_assignment.updated_by = request.user
                
                edit_assignment.clean()
                edit_assignment.save()
                messages.success(request, f'Shift assignment for {employee.first_name} updated successfully!')
            else:
                new_assignment = ShiftAssignment(
                    organization=request.user.organization,
                    employee=employee,
                    shift=shift,
                    effective_from=effective_from,
                    effective_to=effective_to,
                    created_by=request.user
                )
                new_assignment.clean()
                new_assignment.save()
                messages.success(request, f'Shift assigned to {employee.first_name} successfully!')
                
        except (Employee.DoesNotExist, Shift.DoesNotExist):
            messages.error(request, "Selected Employee or Shift does not exist.")
        except ValidationError as e:
            msg = e.messages[0] if hasattr(e, 'messages') else str(e)
            messages.error(request, msg)
        except Exception as e:
            messages.error(request, f"An error occurred: {str(e)}")
            
        return redirect('assign_shift')

    context = {
        'edit_assignment': edit_assignment,
        'employees': Employee.objects.filter(organization=request.user.organization, is_deleted=False).order_by('first_name'),
        'shifts': Shift.objects.filter(organization=request.user.organization, is_deleted=False).order_by('name'),
        'assignments': ShiftAssignment.objects.filter(organization=request.user.organization, is_deleted=False).select_related('employee', 'shift').order_by('-created_at'),
    }
    return render(request, 'assignshift.html', context)

from django.contrib.auth.decorators import login_required
from datetime import datetime
from .models import Attendance

@login_required
def clock_in_out_view(request):
    if request.method == 'POST':
        action = request.POST.get('action')
        # Find employee
        employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization, is_active=True, is_deleted=False).first()
        
        if not employee:
            messages.error(request, "Your account is not linked to an active employee profile in this organization.")
            return redirect('home')

        today = datetime.now().date()
        current_time = datetime.now().time()
        
        # Get current shift assignment
        from attendance.models import ShiftAssignment
        from django.db.models import Q
        shift_assignment = ShiftAssignment.objects.filter(
            employee=employee,
            effective_from__lte=today
        ).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gte=today)
        ).first()
        
        shift = shift_assignment.shift if shift_assignment else None
        
        attendance = None
        created = False
        
        if action == 'clock_out':
            attendance = Attendance.objects.filter(employee=employee, date=today, clock_out__isnull=True).first()
            if not attendance:
                yesterday = today - timedelta(days=1)
                attendance = Attendance.objects.filter(employee=employee, date=yesterday, clock_out__isnull=True, shift__is_night_shift=True).first()
                
        if not attendance:
            attendance, created = Attendance.objects.get_or_create(
                employee=employee,
                date=today,
                defaults={
                    'organization': employee.organization,
                    'shift': shift
                }
            )
        
        # If record already existed but shift was missing, update it
        if not attendance.shift and shift:
            attendance.shift = shift
            attendance.save()
        
        if action == 'clock_in':
            if attendance.clock_in:
                messages.warning(request, "You have already clocked in today.")
            else:
                attendance.clock_in = current_time
                
                # Calculate Late Minutes
                if attendance.shift:
                    shift_start = datetime.combine(attendance.date, attendance.shift.start_time)
                    actual_in = datetime.combine(today, current_time)
                    
                    if actual_in > shift_start:
                        diff = actual_in - shift_start
                        late_mins = int(diff.total_seconds() / 60)
                        if late_mins > attendance.shift.grace_minutes:
                            attendance.late_minutes = late_mins
                
                attendance.save()
                messages.success(request, f"Successfully clocked in at {current_time.strftime('%I:%M %p')}.")
        elif action == 'clock_out':
            if not attendance.clock_in:
                messages.warning(request, "You need to clock in first.")
            elif attendance.clock_out:
                messages.warning(request, "You have already clocked out today.")
            else:
                attendance.clock_out = current_time
                
                # Calculate Early Out Minutes
                if attendance.shift:
                    shift_end = datetime.combine(attendance.date, attendance.shift.end_time)
                    if attendance.shift.is_night_shift:
                        shift_end += timedelta(days=1)
                        
                    actual_out = datetime.combine(today, current_time)
                    
                    if actual_out < shift_end:
                        diff = shift_end - actual_out
                        attendance.early_out_minutes = int(diff.total_seconds() / 60)
                
                # Calculate Total Work Hours
                t1 = datetime.combine(attendance.date, attendance.clock_in)
                # if clocked in late night and now it's next day
                if today > attendance.date and attendance.clock_in < current_time:
                    # Actually, we know t1's true date is today - 1 (or attendance.date)
                    pass
                t2 = datetime.combine(today, current_time)
                
                if t2 < t1:
                    t2 += timedelta(days=1)
                    
                delta = t2 - t1
                attendance.total_work_hours = delta.total_seconds() / 3600.0
                
                attendance.save()
                messages.success(request, f"Successfully clocked out at {current_time.strftime('%I:%M %p')}.")
                
    return redirect('home')

@login_required
def request_correction_view(request, attendance_id):
    attendance = get_object_or_404(Attendance, id=attendance_id, employee__email=request.user.email)
    
    if request.method == 'POST':
        requested_in = request.POST.get('requested_in')
        requested_out = request.POST.get('requested_out')
        reason = request.POST.get('reason')
        
        if not reason:
            messages.error(request, "Reason is required.")
            return redirect('attendance')
            
        time_in = None
        time_out = None
        try:
            if requested_in:
                time_in = datetime.strptime(requested_in, '%H:%M').time()
            if requested_out:
                time_out = datetime.strptime(requested_out, '%H:%M').time()
        except ValueError:
            messages.error(request, "Invalid time format.")
            return redirect('attendance')
            
        AttendanceCorrection.objects.create(
            attendance=attendance,
            employee=attendance.employee,
            requested_clock_in=time_in,
            requested_clock_out=time_out,
            reason=reason
        )
        messages.success(request, "Correction request submitted successfully.")
    
    return redirect('attendance')

@login_required
def manage_corrections_view(request):
    if not request.user.is_staff:
        messages.error(request, "Access denied.")
        return redirect('home')
        
    corrections = AttendanceCorrection.objects.filter(employee__organization=request.user.organization, status='PENDING').order_by('-created_at')
    
    context = {
        'corrections': corrections
    }
    return render(request, 'manage_corrections.html', context)

@login_required
def resolve_correction_view(request, correction_id):
    if not request.user.is_staff:
        messages.error(request, "Access denied.")
        return redirect('home')
        
    correction = get_object_or_404(AttendanceCorrection, id=correction_id, employee__organization=request.user.organization)
    
    if request.method == 'POST':
        from django.utils import timezone
        action = request.POST.get('action')
        now = timezone.now()
        
        if action == 'APPROVE':
            correction.status = 'APPROVED'
            correction.resolved_by = request.user
            correction.resolved_at = now
            correction.save()
            
            att = correction.attendance
            if correction.requested_clock_in:
                att.clock_in = correction.requested_clock_in
            if correction.requested_clock_out:
                att.clock_out = correction.requested_clock_out
                
            if att.shift and att.clock_in:
                shift_start = datetime.combine(att.date, att.shift.start_time)
                actual_in = datetime.combine(att.date, att.clock_in)
                # If night shift and clock in is early morning
                if att.shift.is_night_shift and att.clock_in < att.shift.start_time and att.clock_in < time(12,0):
                    actual_in += timedelta(days=1)
                    
                if actual_in > shift_start:
                    diff = actual_in - shift_start
                    late_mins = int(diff.total_seconds() / 60)
                    if late_mins > att.shift.grace_minutes:
                        att.late_minutes = late_mins
                    else:
                        att.late_minutes = 0
                else:
                    att.late_minutes = 0
                    
            if att.shift and att.clock_out:
                shift_end = datetime.combine(att.date, att.shift.end_time)
                if att.shift.is_night_shift:
                    shift_end += timedelta(days=1)
                    
                actual_out = datetime.combine(att.date, att.clock_out)
                if att.shift.is_night_shift and att.clock_out < att.shift.start_time:
                    actual_out += timedelta(days=1)
                    
                if actual_out < shift_end:
                    diff = shift_end - actual_out
                    att.early_out_minutes = int(diff.total_seconds() / 60)
                else:
                    att.early_out_minutes = 0
                    
            if att.clock_in and att.clock_out:
                t1 = datetime.combine(att.date, att.clock_in)
                if att.shift and att.shift.is_night_shift and att.clock_in < att.shift.start_time and att.clock_in < time(12,0):
                    t1 += timedelta(days=1)
                    
                t2 = datetime.combine(att.date, att.clock_out)
                if t2 < t1:
                    t2 += timedelta(days=1)
                    
                delta = t2 - t1
                att.total_work_hours = delta.total_seconds() / 3600.0
                
            att.save()
            messages.success(request, "Correction approved and attendance updated.")
            
        elif action == 'REJECT':
            correction.status = 'REJECTED'
            correction.resolved_by = request.user
            correction.resolved_at = now
            correction.save()
            messages.success(request, "Correction request rejected.")
            
    return redirect('manage_corrections')

@login_required
def break_toggle_view(request):
    from django.utils import timezone
    today = timezone.now().date()
    employee = Employee.objects.filter(email=request.user.email, is_active=True, is_deleted=False).first()
    if not employee:
        messages.error(request, "Employee record not found.")
        return redirect('home')
        
    attendance = Attendance.objects.filter(employee=employee, date=today).first()
    if not attendance or not attendance.clock_in:
        messages.error(request, "You must be clocked in to take a break.")
        return redirect('home')
        
    if attendance.clock_out:
        messages.error(request, "You have already clocked out for today.")
        return redirect('home')
        
    from .models import BreakLog
    active_break = BreakLog.objects.filter(attendance=attendance, end_time__isnull=True).first()
    
    if active_break:
        now = timezone.now()
        active_break.end_time = now
        delta = now - active_break.start_time
        active_break.duration_minutes = int(delta.total_seconds() / 60)
        active_break.save()
        
        all_breaks = BreakLog.objects.filter(attendance=attendance, end_time__isnull=False)
        total_mins = sum(b.duration_minutes for b in all_breaks)
        attendance.total_break_minutes = total_mins
        
        if attendance.clock_in:
            t1 = timezone.make_aware(datetime.combine(attendance.date, attendance.clock_in))
            t2 = now
            gross_seconds = (t2 - t1).total_seconds()
            net_seconds = gross_seconds - (total_mins * 60)
            attendance.net_work_hours = max(0, net_seconds / 3600.0)
            
        attendance.save()
        messages.success(request, f"Break ended. Duration: {active_break.duration_minutes} mins.")
    else:
        BreakLog.objects.create(attendance=attendance)
        messages.success(request, "Break started. Stay refreshed!")
        
    return redirect('home')

@login_required
def attendance_calendar_view(request):
    organization = request.user.organization
    
    # Staff can view any employee's calendar, others only their own
    employee_id = request.GET.get('employee_id')
    if request.user.is_staff and employee_id:
        employee = get_object_or_404(Employee, id=employee_id, organization=organization)
    else:
        employee = Employee.objects.filter(email=request.user.email, organization=organization, is_active=True, is_deleted=False).first()
    
    if not employee:
        messages.error(request, "Employee profile not found.")
        return redirect('home')

    # Get month and year from GET parameters or use current
    today = timezone.now().date()
    year = int(request.GET.get('year', today.year))
    month = int(request.GET.get('month', today.month))
    
    # Calculate prev/next month
    first_day = date(year, month, 1)
    prev_month_date = first_day - timedelta(days=1)
    next_month_date = (first_day + timedelta(days=32)).replace(day=1)
    
    # Get all attendance for this employee in this month
    attendances = Attendance.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month
    )
    attendance_map = {att.date: att for att in attendances}
    
    # Get holidays
    from leaves.models import Holiday
    holidays = Holiday.objects.filter(
        organization=organization,
        date__year=year,
        date__month=month
    )
    holiday_map = {h.date: h for h in holidays}
    
    # Build calendar
    cal = calendar.Calendar(firstweekday=6) # Sunday start
    month_days = cal.monthdays2calendar(year, month)
    
    # Process days for template
    processed_calendar = []
    for week in month_days:
        week_days = []
        for day_num, weekday in week:
            if day_num == 0:
                week_days.append({'day': 0, 'status': 'empty'})
            else:
                curr_date = date(year, month, day_num)
                att = attendance_map.get(curr_date)
                hol = holiday_map.get(curr_date)
                
                status = 'none'
                label = ''
                
                if hol:
                    status = 'holiday'
                    label = hol.name
                elif att:
                    if att.late_minutes > 0:
                        status = 'late'
                    elif att.clock_in:
                        status = 'present'
                    else:
                        status = 'absent'
                elif curr_date < today:
                    # If past date and no attendance/holiday, mark as absent if it's a weekday
                    if curr_date.weekday() < 5: # Mon-Fri
                         status = 'absent'
                    else:
                         status = 'weekend'
                
                week_days.append({
                    'day': day_num,
                    'date': curr_date,
                    'status': status,
                    'label': label,
                    'attendance': att
                })
        processed_calendar.append(week_days)
    
    # For staff, get list of employees for selector
    employees = None
    if request.user.is_staff:
        employees = Employee.objects.filter(organization=organization, is_deleted=False).order_by('first_name')
        
    context = {
        'calendar': processed_calendar,
        'year': year,
        'month': month,
        'month_name': calendar.month_name[month],
        'prev_year': prev_month_date.year,
        'prev_month': prev_month_date.month,
        'next_year': next_month_date.year,
        'next_month': next_month_date.month,
        'today': today,
        'employee': employee,
        'employees': employees,
    }
    
    return render(request, 'attendance_calendar.html', context)

@login_required
def export_attendance_view(request):
    if not request.user.is_staff:
        messages.error(request, "Access denied.")
        return redirect('home')
        
    organization = request.user.organization
    export_range = request.GET.get('range', 'today')
    export_format = request.GET.get('format', 'excel')
    
    today = timezone.now().date()
    start_date = today
    end_date = today
    
    if export_range == 'today':
        start_date = today
        end_date = today
    elif export_range == 'week':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif export_range == 'month':
        start_date = today.replace(day=1)
        end_date = today
    elif export_range == 'custom':
        s_str = request.GET.get('start_date')
        e_str = request.GET.get('end_date')
        try:
            start_date = datetime.strptime(s_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(e_str, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            messages.error(request, "Invalid date range.")
            return redirect('attendance')
            
    attendances = Attendance.objects.filter(
        employee__organization=organization, 
        date__range=[start_date, end_date]
    ).select_related('employee', 'employee__department').order_by('-date', 'employee__first_name')
    
    import io
    from django.http import HttpResponse

    if export_format == 'excel':
        import xlsxwriter
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output)
        worksheet = workbook.add_worksheet("Attendance Report")
        
        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#4F46E5', 'font_color': 'white', 'border': 1})
        border_fmt = workbook.add_format({'border': 1})
        
        headers = ['Date', 'Employee ID', 'Name', 'Department', 'Clock In', 'Clock Out', 'Gross Hours', 'Break (M)', 'Net Hours', 'Status']
        for col, text in enumerate(headers):
            worksheet.write(0, col, text, header_fmt)
            
        for row, log in enumerate(attendances, start=1):
            worksheet.write(row, 0, log.date.strftime('%Y-%m-%d'), border_fmt)
            worksheet.write(row, 1, log.employee.employee_id, border_fmt)
            worksheet.write(row, 2, f"{log.employee.first_name} {log.employee.last_name}", border_fmt)
            worksheet.write(row, 3, log.employee.department.name if log.employee.department else "--", border_fmt)
            worksheet.write(row, 4, log.clock_in.strftime('%I:%M %p') if log.clock_in else "--", border_fmt)
            worksheet.write(row, 5, log.clock_out.strftime('%I:%M %p') if log.clock_out else "--", border_fmt)
            worksheet.write(row, 6, log.current_work_time, border_fmt)
            worksheet.write(row, 7, log.total_break_minutes or 0, border_fmt)
            worksheet.write(row, 8, f"{log.net_work_hours:.2f}h" if log.net_work_hours else log.current_work_time, border_fmt)
            
            status = "Absent"
            if log.clock_in and log.clock_out: status = "Completed"
            elif log.clock_in: status = "Working"
            worksheet.write(row, 9, status, border_fmt)
            
        worksheet.set_column(0, 9, 15)
        workbook.close()
        output.seek(0)
        
        response = HttpResponse(output.read(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        response['Content-Disposition'] = f'attachment; filename="Attendance_{start_date}_to_{end_date}.xlsx"'
        return response

    elif export_format == 'pdf':
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import landscape, A4
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet

        output = io.BytesIO()
        doc = SimpleDocTemplate(output, pagesize=landscape(A4))
        elements = []
        styles = getSampleStyleSheet()
        
        elements.append(Paragraph(f"Attendance Report: {start_date} to {end_date}", styles['Title']))
        elements.append(Spacer(1, 12))
        
        data = [['Date', 'Emp ID', 'Name', 'Dept', 'In', 'Out', 'Gross', 'Break', 'Net', 'Status']]
        for log in attendances:
            status = "Absent"
            if log.clock_in and log.clock_out: status = "Completed"
            elif log.clock_in: status = "Working"
            
            data.append([
                log.date.strftime('%d/%m'),
                log.employee.employee_id,
                f"{log.employee.first_name} {log.employee.last_name}"[:20],
                log.employee.department.name[:10] if log.employee.department else "--",
                log.clock_in.strftime('%I:%M%p') if log.clock_in else "--",
                log.clock_out.strftime('%I:%M%p') if log.clock_out else "--",
                log.current_work_time,
                str(log.total_break_minutes or 0),
                f"{log.net_work_hours:.2f}h" if log.net_work_hours else log.current_work_time,
                status
            ])
            
        t = Table(data, repeatRows=1)
        t.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4F46E5')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        elements.append(t)
        doc.build(elements)
        
        output.seek(0)
        response = HttpResponse(output.read(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="Attendance_{start_date}_to_{end_date}.pdf"'
        return response

    return redirect('attendance')

from django.db.models import Avg, Sum, Count, Q
from django.utils import timezone
from datetime import timedelta

@login_required
def attendance_analytics_view(request):
    if not request.user.is_staff:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("You are not authorized to view this page.")
        
    today = timezone.localdate()
    start_of_month = today.replace(day=1)
    
    month_attendances = Attendance.objects.filter(date__gte=start_of_month, date__lte=today)
    
    from employees.models import Employee, Department
    total_employees = Employee.objects.count()
    
    today_attendances = Attendance.objects.filter(date=today)
    present_today = today_attendances.filter(clock_in__isnull=False).count()
    absent_today = total_employees - present_today
    
    total_punches = month_attendances.filter(clock_in__isnull=False).count()
    late_punches = month_attendances.filter(late_minutes__gt=0).count()
    early_departures = month_attendances.filter(early_out_minutes__gt=0).count()
    on_time_punches = total_punches - late_punches
    
    punctuality_percent = 0
    if total_punches > 0:
        punctuality_percent = round((on_time_punches / total_punches) * 100, 1)
        
    avg_hours_decimal = month_attendances.aggregate(avg=Avg('net_work_hours'))['avg']
    avg_hours = round(avg_hours_decimal, 1) if avg_hours_decimal else 0
    
    # 7-Day Trend
    last_7_days = [today - timedelta(days=i) for i in range(6, -1, -1)]
    trend_labels = [d.strftime('%b %d') for d in last_7_days]
    
    trend_present = []
    trend_late = []
    trend_overtime = []
    
    for d in last_7_days:
        day_att = Attendance.objects.filter(date=d)
        p_count = day_att.filter(clock_in__isnull=False).count()
        l_count = day_att.filter(late_minutes__gt=0).count()
        o_hours = day_att.aggregate(total=Sum('overtime_hours'))['total'] or 0
        trend_present.append(p_count)
        trend_late.append(l_count)
        trend_overtime.append(float(o_hours))
        
    # Department Wise Attendance
    departments = Department.objects.filter(organization=request.user.organization, is_deleted=False)
    dept_labels = []
    dept_present_rates = []
    
    for dept in departments:
        dept_emps = Employee.objects.filter(department=dept, is_active=True).count()
        if dept_emps > 0:
            dept_att = today_attendances.filter(employee__department=dept, clock_in__isnull=False).count()
            rate = round((dept_att / dept_emps) * 100, 1)
            dept_labels.append(dept.name)
            dept_present_rates.append(rate)

    # Top Latecomers
    late_list = month_attendances.filter(late_minutes__gt=0).values('employee__first_name', 'employee__last_name').annotate(total_late=Sum('late_minutes'), times_late=Count('id')).order_by('-total_late')[:5]

    context = {
        'total_employees': total_employees,
        'present_today': present_today,
        'absent_today': absent_today,
        'punctuality_percent': punctuality_percent,
        'avg_hours': avg_hours,
        'early_departures': early_departures,
        'trend_labels': trend_labels,
        'trend_present': trend_present,
        'trend_late': trend_late,
        'trend_overtime': trend_overtime,
        'dept_labels': dept_labels,
        'dept_present_rates': dept_present_rates,
        'late_list': late_list,
    }
    
    return render(request, 'attendance_analytics.html', context)

@login_required
def overtime_dashboard_view(request):
    from employees.models import Employee
    from .models import OvertimeRequest
    
    employee = Employee.objects.filter(email=request.user.email, is_active=True, is_deleted=False).first()
    
    if request.method == 'POST' and employee:
        date = request.POST.get('date')
        hours = request.POST.get('hours')
        reason = request.POST.get('reason')
        
        if date and hours and reason:
            OvertimeRequest.objects.create(
                employee=employee,
                date=date,
                hours_requested=hours,
                reason=reason,
                created_by=request.user
            )
            messages.success(request, "Overtime request submitted successfully.")
            return redirect('overtime_dashboard')
            
    if employee and not request.user.is_staff:
        requests_list = OvertimeRequest.objects.filter(employee=employee).order_by('-created_at')
        pending_requests = None
        
    elif request.user.is_staff:
        requests_list = OvertimeRequest.objects.filter(employee__organization=request.user.organization).order_by('-created_at')
        pending_requests = OvertimeRequest.objects.filter(employee__organization=request.user.organization, status='PENDING').order_by('-created_at')
        
    else:
        requests_list = []
        pending_requests = None
        
    context = {
        'requests': requests_list,
        'pending_requests': pending_requests,
        'employee': employee,
    }
    
    return render(request, 'overtime_dashboard.html', context)

@login_required
def overtime_action_view(request, request_id):
    if not request.user.is_staff:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Access Denied")
        
    from .models import OvertimeRequest
    from django.shortcuts import get_object_or_404
    
    ot_request = get_object_or_404(OvertimeRequest, id=request_id)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'APPROVE':
            ot_request.status = 'APPROVED'
            ot_request.approved_by = request.user
            ot_request.save()
            messages.success(request, "Overtime approved.")
            
            att = Attendance.objects.filter(employee=ot_request.employee, date=ot_request.date).first()
            if att:
                att.overtime_hours = float(att.overtime_hours) + float(ot_request.hours_requested)
                att.save()
                
        elif action == 'REJECT':
            ot_request.status = 'REJECTED'
            ot_request.approved_by = request.user
            ot_request.save()
            messages.success(request, "Overtime rejected.")
            
    return redirect('overtime_dashboard')


