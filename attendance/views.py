from django.shortcuts import render , redirect
from django.contrib import messages
from django.http import HttpResponse
from .models import Shift, ShiftAssignment
from django.core.exceptions import ValidationError
from employees.models import Employee

# Create your views here.
def attendance_view(request):
    return HttpResponse("welcome to attendance")
def create_shift_view(request,pk=None):
    edit_shift = None
    
    # Handle edit query parameter
    if not pk and request.GET.get('edit'):
        pk = request.GET.get('edit')
        
    if pk:
        try:
            edit_shift = Shift.objects.get(pk=pk, is_deleted=False)
        except Shift.DoesNotExist:
            messages.error(request, 'Shift not found.')
            return redirect('create_shift')
            
    if request.method == 'POST':
        # Handle delete
        delete_id = request.GET.get('delete')
        if delete_id:
            try:
                shift_to_delete = Shift.objects.get(pk=delete_id, is_deleted=False)
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
        existing_shift = Shift.objects.filter(name__iexact=name).first()
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
        'shifts': Shift.objects.filter(is_deleted=False).order_by('-created_at'),
    }
    return render(request, 'createshift.html', context)

def assign_shift_view(request, pk=None):
    edit_assignment = None
    
    if not pk and request.GET.get('edit'):
        pk = request.GET.get('edit')
        
    if pk:
        try:
            edit_assignment = ShiftAssignment.objects.get(pk=pk, is_deleted=False)
        except ShiftAssignment.DoesNotExist:
            messages.error(request, 'Shift assignment not found.')
            return redirect('assign_shift')
            
    if request.method == 'POST':
        # Handle delete
        delete_id = request.GET.get('delete')
        if delete_id:
            try:
                assignment_to_delete = ShiftAssignment.objects.get(pk=delete_id, is_deleted=False)
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
            employee = Employee.objects.get(pk=employee_id, is_deleted=False)
            shift = Shift.objects.get(pk=shift_id, is_deleted=False)
            
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
        'employees': Employee.objects.filter(is_deleted=False).order_by('first_name'),
        'shifts': Shift.objects.filter(is_deleted=False).order_by('name'),
        'assignments': ShiftAssignment.objects.filter(is_deleted=False).select_related('employee', 'shift').order_by('-created_at'),
    }
    return render(request, 'assignshift.html', context)