from django import forms
from django.utils import timezone

from employees.models import Employee

from .models import JoiningLetter


class JoiningLetterForm(forms.ModelForm):
    class Meta:
        model = JoiningLetter
        fields = [
            'letter_type',
            'employee',
            'candidate_name',
            'candidate_email',
            'candidate_phone',
            'issue_date',
            'joining_date',
            'employment_type',
            'department',
            'designation',
            'work_location',
            'reporting_manager',
            'annual_ctc',
            'probation_period',
            'subject',
            'body',
            'signature_name',
            'signature_title',
            'status',
        ]
        widgets = {
            'letter_type': forms.Select(attrs={'class': 'jl-select', 'data-preview-field': 'letterType'}),
            'employee': forms.Select(attrs={'class': 'jl-select'}),
            'candidate_name': forms.TextInput(attrs={'class': 'jl-input', 'placeholder': 'Candidate / employee name', 'data-preview-field': 'candidateName'}),
            'candidate_email': forms.EmailInput(attrs={'class': 'jl-input', 'placeholder': 'candidate@example.com', 'data-preview-field': 'candidateEmail'}),
            'candidate_phone': forms.TextInput(attrs={'class': 'jl-input', 'placeholder': 'Phone number', 'data-preview-field': 'candidatePhone'}),
            'issue_date': forms.DateInput(attrs={'class': 'jl-input', 'type': 'date', 'data-preview-field': 'issueDate'}),
            'joining_date': forms.DateInput(attrs={'class': 'jl-input', 'type': 'date', 'data-preview-field': 'joiningDate'}),
            'employment_type': forms.TextInput(attrs={'class': 'jl-input', 'placeholder': 'Full Time / Contract', 'data-preview-field': 'employmentType'}),
            'department': forms.TextInput(attrs={'class': 'jl-input', 'placeholder': 'Department', 'data-preview-field': 'department'}),
            'designation': forms.TextInput(attrs={'class': 'jl-input', 'placeholder': 'Designation', 'data-preview-field': 'designation'}),
            'work_location': forms.TextInput(attrs={'class': 'jl-input', 'placeholder': 'Work location', 'data-preview-field': 'workLocation'}),
            'reporting_manager': forms.TextInput(attrs={'class': 'jl-input', 'placeholder': 'Reporting manager', 'data-preview-field': 'reportingManager'}),
            'annual_ctc': forms.NumberInput(attrs={'class': 'jl-input', 'step': '0.01', 'placeholder': 'Annual CTC', 'data-preview-field': 'annualCtc'}),
            'probation_period': forms.TextInput(attrs={'class': 'jl-input', 'data-preview-field': 'probationPeriod'}),
            'subject': forms.TextInput(attrs={'class': 'jl-input', 'data-preview-field': 'subject'}),
            'body': forms.Textarea(attrs={'class': 'jl-textarea jl-body-field', 'placeholder': 'Optional extra terms or notes. The letter preview is pre-built.', 'data-preview-field': 'body'}),
            'signature_name': forms.TextInput(attrs={'class': 'jl-input', 'data-preview-field': 'signatureName'}),
            'signature_title': forms.TextInput(attrs={'class': 'jl-input', 'data-preview-field': 'signatureTitle'}),
            'status': forms.Select(attrs={'class': 'jl-select'}),
        }

    def __init__(self, *args, organization=None, **kwargs):
        super().__init__(*args, **kwargs)
        employee_qs = Employee.objects.none()
        if organization:
            employee_qs = Employee.objects.filter(
                organization=organization,
                is_active=True,
                is_deleted=False,
            ).order_by('first_name', 'last_name', 'employee_id')
        self.fields['employee'].queryset = employee_qs
        self.fields['employee'].empty_label = 'Manual candidate / select employee'
        self.fields['letter_type'].choices = JoiningLetter.LETTER_TYPE_CHOICES
        self.fields['body'].required = False
        if not self.instance.pk:
            self.fields['issue_date'].initial = timezone.localdate()
            self.fields['subject'].initial = 'Offer Letter'
            self.fields['letter_type'].initial = 'OFFER'

    def clean(self):
        cleaned = super().clean()
        employee = cleaned.get('employee')
        candidate_name = (cleaned.get('candidate_name') or '').strip()
        if not candidate_name and employee:
            cleaned['candidate_name'] = f"{employee.first_name} {employee.last_name}".strip()
        if not cleaned.get('candidate_name'):
            raise forms.ValidationError("Candidate name is required.")
        return cleaned
