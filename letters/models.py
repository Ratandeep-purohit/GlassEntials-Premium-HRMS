from django.db import models

from employees.models import BaseModel, Employee


class JoiningLetter(BaseModel):
    LETTER_TYPE_CHOICES = (
        ('OFFER', 'Offer Letter'),
        ('APPOINTMENT', 'Appointment Letter'),
        ('JOINING', 'Joining Letter'),
        ('CONFIRMATION', 'Confirmation Letter'),
        ('PROMOTION', 'Promotion Letter'),
        ('EXPERIENCE', 'Experience Letter'),
        ('RELIEVING', 'Relieving Letter'),
        ('WARNING', 'Warning Letter'),
        ('CUSTOM', 'Custom Letter'),
    )

    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('ISSUED', 'Issued'),
        ('ACCEPTED', 'Accepted'),
        ('CANCELLED', 'Cancelled'),
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='joining_letters',
    )
    letter_type = models.CharField(max_length=30, choices=LETTER_TYPE_CHOICES, default='OFFER', db_index=True)
    letter_number = models.CharField(max_length=30, db_index=True)
    candidate_name = models.CharField(max_length=160)
    candidate_email = models.EmailField(blank=True)
    candidate_phone = models.CharField(max_length=20, blank=True)
    issue_date = models.DateField()
    joining_date = models.DateField()
    employment_type = models.CharField(max_length=40, blank=True)
    department = models.CharField(max_length=120, blank=True)
    designation = models.CharField(max_length=120, blank=True)
    work_location = models.CharField(max_length=140, blank=True)
    reporting_manager = models.CharField(max_length=140, blank=True)
    annual_ctc = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    probation_period = models.CharField(max_length=80, blank=True, default='As per company policy')
    subject = models.CharField(max_length=220, default='Offer Letter')
    body = models.TextField(blank=True)
    custom_fields = models.JSONField(default=list, blank=True)
    signature_name = models.CharField(max_length=140, blank=True, default='HR Department')
    signature_title = models.CharField(max_length=140, blank=True, default='Human Resources')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    class Meta:
        db_table = 'letters_letter'
        unique_together = ('organization', 'letter_number')
        ordering = ['-issue_date', '-created_at']
        indexes = [
            models.Index(fields=['organization', 'letter_number']),
            models.Index(fields=['organization', 'joining_date']),
            models.Index(fields=['organization', 'letter_type']),
            models.Index(fields=['status']),
        ]

    def __str__(self):
        return f"{self.letter_number} - {self.candidate_name}"

    @property
    def company_name(self):
        return self.organization.name if self.organization else 'Company'

    def default_body(self):
        joining_date = self.joining_date.strftime('%d %B %Y') if self.joining_date else 'your joining date'
        ctc_line = ''
        if self.annual_ctc is not None:
            ctc_line = f"\nYour annual CTC will be INR {self.annual_ctc:,.2f}, subject to statutory deductions and company policy."

        if self.letter_type == 'APPOINTMENT':
            return (
                f"Dear {self.candidate_name},\n\n"
                f"We are pleased to appoint you as {self.designation or 'the assigned role'} "
                f"in the {self.department or 'assigned'} department at {self.company_name}.\n\n"
                f"Your appointment will be effective from {joining_date}. You will be based at "
                f"{self.work_location or 'the assigned work location'} and will report to "
                f"{self.reporting_manager or 'the reporting manager assigned by the company'}."
                f"{ctc_line}\n\n"
                f"Your employment type will be {self.employment_type or 'as discussed'} and your probation period will be "
                f"{self.probation_period or 'as per company policy'}.\n\n"
                "Your appointment will be governed by company policies, confidentiality obligations, attendance rules, "
                "leave rules, payroll rules, and applicable law.\n\n"
                "We welcome you to the organization and wish you success in your role.\n\n"
                "Sincerely,"
            )

        if self.letter_type == 'JOINING':
            return (
                f"Dear {self.candidate_name},\n\n"
                f"We are pleased to confirm your joining with {self.company_name} as "
                f"{self.designation or 'the assigned role'} in the {self.department or 'assigned'} department.\n\n"
                f"Your date of joining is {joining_date}. You will be based at "
                f"{self.work_location or 'the assigned work location'} and will report to "
                f"{self.reporting_manager or 'the reporting manager assigned by the company'}."
                f"{ctc_line}\n\n"
                f"Your employment type will be {self.employment_type or 'as discussed'} and your probation period will be "
                f"{self.probation_period or 'as per company policy'}.\n\n"
                "Please carry all required identity, education, experience, bank, and statutory documents on your joining day. "
                "Your employment will be governed by company policies, confidentiality obligations, attendance rules, leave rules, "
                "payroll rules, and applicable law.\n\n"
                "We welcome you to the team and look forward to your contribution.\n\n"
                "Sincerely,"
            )

        if self.letter_type == 'CONFIRMATION':
            return (
                f"Dear {self.candidate_name},\n\n"
                f"We are pleased to confirm your employment with {self.company_name} as "
                f"{self.designation or 'the assigned role'} in the {self.department or 'assigned'} department.\n\n"
                f"Your confirmation is effective from {joining_date}. You will continue to be based at "
                f"{self.work_location or 'the assigned work location'} and will report to "
                f"{self.reporting_manager or 'the reporting manager assigned by the company'}."
                f"{ctc_line}\n\n"
                f"Your employment type will remain {self.employment_type or 'as per company records'}. "
                "All terms of employment, confidentiality obligations, attendance rules, leave rules, payroll rules, "
                "and company policies will continue to apply.\n\n"
                "We appreciate your contribution and look forward to your continued growth with the organization.\n\n"
                "Sincerely,"
            )

        if self.letter_type == 'PROMOTION':
            return (
                f"Dear {self.candidate_name},\n\n"
                f"We are pleased to inform you of your promotion to {self.designation or 'the new assigned role'} "
                f"in the {self.department or 'assigned'} department at {self.company_name}.\n\n"
                f"Your promotion will be effective from {joining_date}. You will be based at "
                f"{self.work_location or 'the assigned work location'} and will report to "
                f"{self.reporting_manager or 'the reporting manager assigned by the company'}."
                f"{ctc_line}\n\n"
                "Your revised responsibilities, compensation, benefits, and reporting structure will be governed by "
                "company policy and the terms communicated by Human Resources.\n\n"
                "We appreciate your contribution and wish you continued success in your new role.\n\n"
                "Sincerely,"
            )

        if self.letter_type == 'EXPERIENCE':
            return (
                f"To whom it may concern,\n\n"
                f"This is to certify that {self.candidate_name} was employed with {self.company_name} as "
                f"{self.designation or 'the assigned role'} in the {self.department or 'assigned'} department.\n\n"
                f"As per company records, this certificate is issued on {joining_date}. The employee was associated with "
                f"{self.work_location or 'the assigned work location'} and reported to "
                f"{self.reporting_manager or 'the reporting manager assigned by the company'}.\n\n"
                "This certificate is issued based on records available with the organization and is intended for official use.\n\n"
                "We wish the employee success in future endeavors.\n\n"
                "Sincerely,"
            )

        if self.letter_type == 'RELIEVING':
            return (
                f"Dear {self.candidate_name},\n\n"
                f"This is to confirm that you are relieved from your position as "
                f"{self.designation or 'the assigned role'} in the {self.department or 'assigned'} department at "
                f"{self.company_name}.\n\n"
                f"Your relieving date is {joining_date}. Your final settlement, asset clearance, access closure, "
                "and statutory processing will be handled as per company policy.\n\n"
                "Your confidentiality and information protection obligations will continue after separation.\n\n"
                "We thank you for your contribution and wish you success in your future endeavors.\n\n"
                "Sincerely,"
            )

        if self.letter_type == 'WARNING':
            return (
                f"Dear {self.candidate_name},\n\n"
                f"This letter serves as a formal warning regarding your conduct, performance, or policy compliance "
                f"in the role of {self.designation or 'the assigned role'} in the "
                f"{self.department or 'assigned'} department at {self.company_name}.\n\n"
                f"This warning is effective from {joining_date}. You are expected to take immediate corrective action "
                "and comply with company policies, manager instructions, and code of conduct expectations.\n\n"
                "Repeated non-compliance may result in further disciplinary action as per company policy.\n\n"
                "Please acknowledge receipt of this warning.\n\n"
                "Sincerely,"
            )

        if self.letter_type == 'CUSTOM':
            return self.body or (
                f"Dear {self.candidate_name},\n\n"
                "Write your custom letter content here.\n\n"
                "Sincerely,"
            )

        return (
            f"Dear {self.candidate_name},\n\n"
            f"We are pleased to offer you employment with {self.company_name} as "
            f"{self.designation or 'the assigned role'} in the {self.department or 'assigned'} department.\n\n"
            f"Your proposed date of joining is {joining_date}. You will be based at "
            f"{self.work_location or 'the assigned work location'} and will report to "
            f"{self.reporting_manager or 'the reporting manager assigned by the company'}."
            f"{ctc_line}\n\n"
            f"Your employment type will be {self.employment_type or 'as discussed'} and your probation period will be "
            f"{self.probation_period or 'as per company policy'}.\n\n"
            "This offer is subject to successful verification of identity, education, experience, references, "
            "and acceptance of company policies including confidentiality and information security obligations.\n\n"
            "We are excited about the possibility of you joining our team and look forward to your acceptance.\n\n"
            "Sincerely,"
        )
