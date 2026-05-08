from django.db import models
from django.conf import settings
from employees.models import BaseModel, Employee

class Location(BaseModel):
    """
    Geographic or office-based locations to handle multi-regional compliance and holiday calendars.
    """
    name = models.CharField(max_length=100)
    timezone = models.CharField(max_length=50, default='UTC')
    country_code = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2")

    def __str__(self):
        return f"{self.name} ({self.country_code})"

class LeaveType(BaseModel):
    """
    Categorization of leaves (e.g., Sick, Annual, Bereavement).
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10)
    description = models.TextField(blank=True)
    is_paid = models.BooleanField(default=True)
    is_statutory = models.BooleanField(default=False)

    def __str__(self):
        return self.name

class LeavePolicy(BaseModel):
    """
    The business logic engine. Decouples rules from types to support multi-regional or dept-specific policies.
    """
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='policies')
    accrual_rate = models.DecimalField(max_digits=5, decimal_places=2, help_text="Days accrued per month")
    max_balance = models.DecimalField(max_digits=5, decimal_places=2)
    carry_forward_limit = models.DecimalField(max_digits=5, decimal_places=2)
    min_service_days = models.PositiveIntegerField(default=0, help_text="Days of employment required before this leave can be used")
    sandwich_rule = models.BooleanField(default=False, help_text="If True, holidays/weekends falling between leave days are counted as leave")
    requires_attachment = models.BooleanField(default=False)
    attachment_threshold_days = models.PositiveIntegerField(default=3, help_text="Attachment required if leave duration exceeds this")

    def __str__(self):
        return f"Policy for {self.leave_type.name} - {self.organization.name if self.organization else 'Global'}"

class LeaveBalance(BaseModel):
    """
    Real-time tracking of employee leave entitlements.
    """
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    current_balance = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    used_balance = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    pending_balance = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)

    class Meta:
        unique_together = ('employee', 'leave_type', 'year')
        indexes = [
            models.Index(fields=['employee', 'leave_type', 'year']),
        ]

    def __str__(self):
        return f"{self.employee.first_name} - {self.leave_type.code}: {self.current_balance}"

class LeaveRequest(BaseModel):
    """
    The core transaction record for a leave application.
    """
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('PENDING', 'Pending Approval'),
        ('MANAGER_APPROVED', 'Approved by Manager'),
        ('APPROVED', 'Fully Approved'),
        ('REJECTED', 'Rejected'),
        ('CANCEL_REQUESTED', 'Cancellation Requested'),
        ('CANCELLED', 'Cancelled'),
    )

    SESSION_CHOICES = (
        ('FULL', 'Full Day'),
        ('MORNING', 'First Half'),
        ('AFTERNOON', 'Second Half'),
        ('SHORT', 'Short Leave (2 Hours)'),
    )


    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()
    end_date = models.DateField()
    session_type = models.CharField(max_length=10, choices=SESSION_CHOICES, default='FULL')
    total_days = models.DecimalField(max_digits=4, decimal_places=1)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    attachment = models.FileField(upload_to='leave_attachments/', blank=True, null=True)
    
    # Time for Short Leave
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    current_handler = models.ForeignKey(

        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='assigned_leaves'
    )


    def __str__(self):
        return f"{self.employee.first_name} - {self.leave_type.code} ({self.start_date})"

class ApprovalWorkflow(BaseModel):
    """
    Supports multi-level approval chains (e.g., Manager -> Dept Head -> HR).
    """
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='workflow_steps')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    sequence_order = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=[('PENDING', 'Pending'), ('APPROVED', 'Approved'), ('REJECTED', 'Rejected')], default='PENDING')
    action_date = models.DateTimeField(null=True, blank=True)
    comments = models.TextField(blank=True)

    class Meta:
        ordering = ['sequence_order']

class LeaveAccrualLog(BaseModel):
    """
    Immutable audit trail for balance adjustments.
    """
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=5, decimal_places=2)
    action_type = models.CharField(max_length=20, choices=[
        ('ACCRUAL', 'Automated Accrual'),
        ('MANUAL', 'Manual Adjustment'),
        ('CARRY_FORWARD', 'Year-end Carry Forward'),
        ('ENCASHMENT', 'Leave Encashment'),
        ('COMP_OFF_CREDIT', 'Comp-off Credit'),
        ('LEAVE_CANCEL_CREDIT', 'Leave Cancellation Credit'),
    ])

    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Holiday(BaseModel):
    """
    Holiday calendar with regional granularity.
    """
    name = models.CharField(max_length=100)
    date = models.DateField()
    location_fk = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    is_optional = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.date})"

class CompOffRequest(BaseModel):
    """
    Handles requests for compensatory off credit for working on weekends or holidays.
    """
    STATUS_CHOICES = (
        ('PENDING', 'Pending Approval'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='compoff_requests')
    worked_date = models.DateField()
    reason = models.TextField(help_text="Describe the work done on this day")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    current_handler = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='assigned_compoffs'
    )

    def __str__(self):
        return f"{self.employee.first_name} - Comp-off for {self.worked_date}"
