from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from employees.models import Employee

from .forms import JoiningLetterForm
from .models import JoiningLetter


def _staff_required(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return False
    return True


def _next_letter_number(organization, letter_type='OFFER'):
    year = timezone.localdate().year
    prefix_map = {
        'OFFER': 'OL',
        'APPOINTMENT': 'AL',
        'JOINING': 'JL',
        'CONFIRMATION': 'CN',
        'PROMOTION': 'PR',
        'EXPERIENCE': 'EX',
        'RELIEVING': 'RL',
        'WARNING': 'WL',
        'CUSTOM': 'CL',
    }
    prefix = f"{prefix_map.get(letter_type, 'LT')}-{year}-"
    last_letter = JoiningLetter.objects.filter(
        organization=organization,
        letter_type=letter_type,
        letter_number__startswith=prefix,
    ).order_by('-letter_number').first()
    if not last_letter:
        return f"{prefix}0001"
    try:
        next_number = int(last_letter.letter_number.rsplit('-', 1)[-1]) + 1
    except (TypeError, ValueError):
        next_number = 1
    return f"{prefix}{next_number:04d}"


def _custom_fields_from_post(post_data):
    labels = post_data.getlist('custom_field_label[]')
    values = post_data.getlist('custom_field_value[]')
    fields = []
    for label, value in zip(labels, values):
        clean_label = (label or '').strip()
        clean_value = (value or '').strip()
        if clean_label or clean_value:
            fields.append({
                'label': clean_label or 'Custom Field',
                'value': clean_value,
            })
    return fields[:40]


def _apply_employee_defaults(letter):
    employee = letter.employee
    if not employee:
        return
    if not letter.candidate_name:
        letter.candidate_name = f"{employee.first_name} {employee.last_name}".strip()
    if not letter.candidate_email:
        letter.candidate_email = employee.email or ''
    if not letter.candidate_phone:
        letter.candidate_phone = employee.phone_number or ''
    if not letter.joining_date and employee.joining_date:
        letter.joining_date = employee.joining_date
    if not letter.employment_type:
        letter.employment_type = employee.employment_type or ''
    if not letter.department and employee.department:
        letter.department = employee.department.name
    if not letter.designation and employee.designation:
        letter.designation = employee.designation.name
    if not letter.work_location:
        letter.work_location = employee.work_location or ''
    if not letter.reporting_manager and employee.manager:
        letter.reporting_manager = f"{employee.manager.first_name} {employee.manager.last_name}".strip()


def _employee_default_payload(organization):
    employees = Employee.objects.filter(
        organization=organization,
        is_active=True,
        is_deleted=False,
    ).select_related('department', 'designation', 'manager').order_by('first_name', 'last_name', 'employee_id')

    payload = {}
    for employee in employees:
        payload[str(employee.id)] = {
            'candidate_name': f"{employee.first_name} {employee.last_name}".strip(),
            'candidate_email': employee.email or '',
            'candidate_phone': employee.phone_number or '',
            'joining_date': employee.joining_date.isoformat() if employee.joining_date else '',
            'employment_type': employee.employment_type or '',
            'department': employee.department.name if employee.department else '',
            'designation': employee.designation.name if employee.designation else '',
            'work_location': employee.work_location or '',
            'reporting_manager': (
                f"{employee.manager.first_name} {employee.manager.last_name}".strip()
                if employee.manager else ''
            ),
        }
    return payload


def _letter_queryset(organization):
    return JoiningLetter.objects.filter(
        organization=organization,
    ).select_related('employee').order_by('-created_at')


@login_required
def letters_dashboard(request):
    if not _staff_required(request):
        return redirect('home')

    organization = request.user.organization
    letters = _letter_queryset(organization)
    total_letters = letters.count()
    issued_letters = letters.filter(status='ISSUED').count()
    draft_letters = letters.filter(status='DRAFT').count()
    accepted_letters = letters.filter(status='ACCEPTED').count()

    return render(request, 'letters/manage.html', {
        'letters': letters,
        'total_letters': total_letters,
        'issued_letters': issued_letters,
        'draft_letters': draft_letters,
        'accepted_letters': accepted_letters,
    })


@login_required
def letter_builder(request, letter_id=None):
    if not _staff_required(request):
        return redirect('home')

    organization = request.user.organization
    edit_letter = None
    if letter_id:
        edit_letter = get_object_or_404(
            JoiningLetter,
            id=letter_id,
            organization=organization,
        )

    if request.method == 'POST':
        form = JoiningLetterForm(request.POST, organization=organization, instance=edit_letter)
        if form.is_valid():
            letter = form.save(commit=False)
            letter.organization = organization
            if not letter.letter_number:
                letter.letter_number = _next_letter_number(organization, letter.letter_type)
                letter.created_by = request.user
            letter.updated_by = request.user
            _apply_employee_defaults(letter)
            if letter.letter_type == 'CUSTOM':
                letter.custom_fields = _custom_fields_from_post(request.POST)
            else:
                letter.custom_fields = []
            letter.save()
            messages.success(request, f"{letter.get_letter_type_display()} {letter.letter_number} saved successfully.")
            return redirect('letters:manage')
        messages.error(request, "Please correct the highlighted letter fields.")
    else:
        initial = {}
        if not edit_letter:
            initial = {
                'letter_type': 'OFFER',
                'issue_date': timezone.localdate(),
                'subject': 'Offer Letter',
                'probation_period': 'As per company policy',
                'signature_name': 'HR Department',
                'signature_title': 'Human Resources',
            }
        form = JoiningLetterForm(instance=edit_letter, initial=initial, organization=organization)

    active_letter_type = 'OFFER'
    if edit_letter:
        active_letter_type = edit_letter.letter_type
    elif request.method == 'POST':
        active_letter_type = request.POST.get('letter_type') or 'OFFER'

    return render(request, 'letters/create.html', {
        'form': form,
        'edit_letter': edit_letter,
        'employee_defaults': _employee_default_payload(organization),
        'letter_types': [
            {'value': value, 'label': label}
            for value, label in JoiningLetter.LETTER_TYPE_CHOICES
        ],
        'next_letter_number': edit_letter.letter_number if edit_letter else _next_letter_number(organization, active_letter_type),
        'organization': organization,
        'custom_fields': edit_letter.custom_fields if edit_letter and edit_letter.custom_fields else [],
    })


@login_required
def manage_letters(request, letter_id=None):
    if letter_id:
        return letter_builder(request, letter_id)
    return letters_dashboard(request)


@login_required
def letter_detail(request, letter_id):
    if not _staff_required(request):
        return redirect('home')

    letter = get_object_or_404(
        JoiningLetter,
        id=letter_id,
        organization=request.user.organization,
    )
    return render(request, 'letters/detail.html', {'letter': letter})


@login_required
def delete_letter(request, letter_id):
    if not _staff_required(request):
        return redirect('home')

    letter = get_object_or_404(
        JoiningLetter,
        id=letter_id,
        organization=request.user.organization,
    )
    if request.method == 'POST':
        letter.is_deleted = True
        letter.is_active = False
        letter.deleted_by = request.user
        letter.deleted_at = timezone.now()
        letter.save()
        messages.success(request, "Letter deleted successfully.")
    return redirect('letters:manage')
