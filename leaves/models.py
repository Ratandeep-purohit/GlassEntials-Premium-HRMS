from django.db import models
from django.conf import settings
from employees.models import BaseModel, Employee

class LeaveCategory(BaseModel):
    """
    Reporting and compliance grouping for leave policies.
    Examples: Paid Leave, Statutory Leave, Unpaid Leave, Comp Off, Optional Holiday.
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    description = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#2563eb")
    is_paid_category = models.BooleanField(default=True)

    class Meta:
        unique_together = ('organization', 'code')
        ordering = ['name']

    def __str__(self):
        return self.name

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
    Enterprise leave policy master. Kept as LeaveType for backward compatibility
    with existing leave requests and balances.
    """
    POLICY_STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('ACTIVE', 'Active'),
        ('INACTIVE', 'Inactive'),
        ('ARCHIVED', 'Archived'),
    )

    category = models.ForeignKey(LeaveCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='leave_types')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10)
    description = models.TextField(blank=True)
    color_tag = models.CharField(max_length=7, default="#2563eb")
    financial_year_start_month = models.PositiveSmallIntegerField(default=4)
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    policy_version = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=POLICY_STATUS_CHOICES, default='ACTIVE')
    is_paid = models.BooleanField(default=True)
    is_statutory = models.BooleanField(default=False)
    is_requestable = models.BooleanField(default=True)
    allow_negative_balance = models.BooleanField(default=False)
    negative_balance_limit = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)

    class Meta:
        unique_together = ('organization', 'code', 'policy_version')
        ordering = ['name']

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

class LeaveAccrualRule(BaseModel):
    FREQUENCY_CHOICES = (
        ('NONE', 'No automatic accrual'),
        ('MONTHLY', 'Monthly'),
        ('QUARTERLY', 'Quarterly'),
        ('HALF_YEARLY', 'Half Yearly'),
        ('YEARLY', 'Yearly'),
        ('JOINING_DATE', 'Joining Date Based'),
        ('MANUAL', 'Manual Only'),
    )
    ROUNDING_CHOICES = (
        ('NONE', 'No Rounding'),
        ('UP', 'Round Up'),
        ('DOWN', 'Round Down'),
        ('NEAREST_HALF', 'Nearest Half Day'),
        ('NEAREST_FULL', 'Nearest Full Day'),
    )

    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='accrual_rule')
    frequency = models.CharField(max_length=20, choices=FREQUENCY_CHOICES, default='MONTHLY')
    accrual_day = models.PositiveSmallIntegerField(default=1)
    accrual_month = models.PositiveSmallIntegerField(null=True, blank=True)
    accrual_rate = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    max_yearly_accrual = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    max_balance_cap = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    prorate_on_joining = models.BooleanField(default=True)
    prorate_on_exit = models.BooleanField(default=True)
    rounding_mode = models.CharField(max_length=20, choices=ROUNDING_CHOICES, default='NONE')
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.leave_type.code} accrual rule"

class LeaveCarryForwardRule(BaseModel):
    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='carry_forward_rule')
    is_allowed = models.BooleanField(default=False)
    max_carry_forward_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    expiry_month = models.PositiveSmallIntegerField(default=3)
    expiry_day = models.PositiveSmallIntegerField(default=31)
    encash_remaining = models.BooleanField(default=False)
    lapse_remaining = models.BooleanField(default=True)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.leave_type.code} carry forward rule"

class LeaveEligibilityRule(BaseModel):
    GENDER_CHOICES = (
        ('ANY', 'Any'),
        ('Male', 'Male'),
        ('Female', 'Female'),
        ('Other', 'Other'),
    )
    EMPLOYEE_FILTER_CHOICES = (
        ('ALL', 'All Eligible Employees'),
        ('INCLUDE', 'Only Included Employees'),
        ('EXCLUDE', 'Exclude Selected Employees'),
    )

    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='eligibility_rule')
    gender = models.CharField(max_length=10, choices=GENDER_CHOICES, default='ANY')
    departments = models.ManyToManyField('employees.Department', blank=True)
    designations = models.ManyToManyField('employees.Designation', blank=True)
    locations = models.ManyToManyField(Location, blank=True)
    employment_types = models.JSONField(default=list, blank=True)
    work_locations = models.JSONField(default=list, blank=True)
    min_service_days = models.PositiveIntegerField(default=0)
    probation_allowed = models.BooleanField(default=True)
    confirmation_required = models.BooleanField(default=False)
    employee_filter_mode = models.CharField(max_length=10, choices=EMPLOYEE_FILTER_CHOICES, default='ALL')
    specific_employees = models.ManyToManyField(Employee, blank=True, related_name='leave_eligibility_rules')
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.leave_type.code} eligibility rule"

class LeaveRestrictionRule(BaseModel):
    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='restriction_rule')
    min_duration = models.DecimalField(max_digits=5, decimal_places=2, default=0.5)
    max_duration = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    max_consecutive_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    min_gap_between_requests = models.PositiveIntegerField(default=0)
    max_requests_per_month = models.PositiveIntegerField(default=0)
    max_requests_per_year = models.PositiveIntegerField(default=0)
    backdate_allowed = models.BooleanField(default=True)
    max_backdate_days = models.PositiveIntegerField(default=0)
    future_date_allowed = models.BooleanField(default=True)
    max_future_days = models.PositiveIntegerField(default=365)
    block_during_payroll_lock = models.BooleanField(default=True)
    block_month_end = models.BooleanField(default=False)
    blackout_periods = models.JSONField(default=list, blank=True)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.leave_type.code} restriction rule"

class LeaveDurationRule(BaseModel):
    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='duration_rule')
    allow_full_day = models.BooleanField(default=True)
    allow_half_day = models.BooleanField(default=True)
    allow_hourly = models.BooleanField(default=False)
    minimum_hourly_unit_minutes = models.PositiveIntegerField(default=60)
    maximum_hourly_duration_minutes = models.PositiveIntegerField(default=480)
    shift_aware = models.BooleanField(default=True)
    allowed_sessions = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.leave_type.code} duration rule"

class LeaveSandwichRule(BaseModel):
    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='sandwich_rule_config')
    count_weekends_between_leave = models.BooleanField(default=False)
    count_holidays_between_leave = models.BooleanField(default=False)
    count_prefix_weekend = models.BooleanField(default=False)
    count_suffix_weekend = models.BooleanField(default=False)
    count_prefix_holiday = models.BooleanField(default=False)
    count_suffix_holiday = models.BooleanField(default=False)
    blocked_clubbing_leave_types = models.ManyToManyField(LeaveType, blank=True, related_name='blocked_by_clubbing_rules')
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.leave_type.code} sandwich rule"

class LeaveProofRule(BaseModel):
    REVIEWER_CHOICES = (
        ('MANAGER', 'Reporting Manager'),
        ('HR', 'HR'),
        ('PAYROLL_ADMIN', 'Payroll Admin'),
    )

    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='proof_rule')
    proof_required = models.BooleanField(default=False)
    required_after_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    allowed_file_types = models.JSONField(default=list, blank=True)
    max_file_size_mb = models.PositiveIntegerField(default=5)
    requires_manual_review = models.BooleanField(default=False)
    reviewer_role = models.CharField(max_length=20, choices=REVIEWER_CHOICES, default='HR')
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.leave_type.code} proof rule"

class LeaveIntegrationRule(BaseModel):
    leave_type = models.OneToOneField(LeaveType, on_delete=models.CASCADE, related_name='integration_rule')
    attendance_sync_enabled = models.BooleanField(default=True)
    prevent_attendance_conflict = models.BooleanField(default=True)
    adjust_late_marks = models.BooleanField(default=True)
    comp_off_generation_enabled = models.BooleanField(default=False)
    payroll_sync_enabled = models.BooleanField(default=True)
    generate_lop = models.BooleanField(default=True)
    negative_balance_deduction = models.BooleanField(default=False)
    enable_encashment = models.BooleanField(default=False)
    final_settlement_encashment = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.leave_type.code} integration rule"

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
    opening_balance = models.DecimalField(max_digits=7, decimal_places=2, default=0.0)
    accrued_balance = models.DecimalField(max_digits=7, decimal_places=2, default=0.0)
    carry_forward_balance = models.DecimalField(max_digits=7, decimal_places=2, default=0.0)
    expired_balance = models.DecimalField(max_digits=7, decimal_places=2, default=0.0)
    encashed_balance = models.DecimalField(max_digits=7, decimal_places=2, default=0.0)
    adjusted_balance = models.DecimalField(max_digits=7, decimal_places=2, default=0.0)
    future_approved_balance = models.DecimalField(max_digits=7, decimal_places=2, default=0.0)
    last_recalculated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('employee', 'leave_type', 'year')
        indexes = [
            models.Index(fields=['employee', 'leave_type', 'year']),
        ]

    def __str__(self):
        return f"{self.employee.first_name} - {self.leave_type.code}: {self.current_balance}"

class LeaveTransaction(BaseModel):
    TRANSACTION_CHOICES = (
        ('OPENING', 'Opening Balance'),
        ('ACCRUAL', 'Accrual'),
        ('RESERVE', 'Reserved for Request'),
        ('CONSUME', 'Consumed on Approval'),
        ('RELEASE', 'Released'),
        ('CARRY_FORWARD', 'Carry Forward'),
        ('EXPIRE', 'Expired'),
        ('ENCASH', 'Encashed'),
        ('ADJUSTMENT', 'Manual Adjustment'),
        ('LOP', 'Loss of Pay'),
    )
    SOURCE_CHOICES = (
        ('SYSTEM', 'System'),
        ('ADMIN', 'Admin'),
        ('EMPLOYEE', 'Employee'),
        ('ATTENDANCE', 'Attendance'),
        ('PAYROLL', 'Payroll'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_transactions')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, related_name='transactions')
    leave_request = models.ForeignKey('LeaveRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='transactions')
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_CHOICES)
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    balance_before = models.DecimalField(max_digits=8, decimal_places=2, default=0.0)
    balance_after = models.DecimalField(max_digits=8, decimal_places=2, default=0.0)
    effective_date = models.DateField()
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='SYSTEM')
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['-effective_date', '-created_at']
        indexes = [
            models.Index(fields=['employee', 'leave_type', 'effective_date']),
            models.Index(fields=['transaction_type', 'source']),
        ]

    def __str__(self):
        return f"{self.employee} {self.leave_type.code} {self.transaction_type} {self.amount}"

class LeaveBalanceSnapshot(BaseModel):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_balance_snapshots')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    snapshot_date = models.DateField()
    current_balance = models.DecimalField(max_digits=8, decimal_places=2, default=0.0)
    used_balance = models.DecimalField(max_digits=8, decimal_places=2, default=0.0)
    pending_balance = models.DecimalField(max_digits=8, decimal_places=2, default=0.0)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ('employee', 'leave_type', 'snapshot_date')
        indexes = [
            models.Index(fields=['employee', 'year', 'snapshot_date']),
        ]

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
        ('WITHDRAWN', 'Withdrawn'),
        ('ESCALATED', 'Escalated'),
    )

    SESSION_CHOICES = (
        ('FULL', 'Full Day'),
        ('MORNING', 'First Half'),
        ('AFTERNOON', 'Second Half'),
        ('SHORT', 'Short Leave (2 Hours)'),
    )


    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    policy_version = models.PositiveIntegerField(default=1)
    request_number = models.CharField(max_length=30, blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    session_type = models.CharField(max_length=10, choices=SESSION_CHOICES, default='FULL')
    total_days = models.DecimalField(max_digits=4, decimal_places=1)
    payable_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    lop_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    attachment = models.FileField(upload_to='leave_attachments/', blank=True, null=True)
    attendance_sync_status = models.CharField(max_length=20, default='PENDING')
    payroll_sync_status = models.CharField(max_length=20, default='PENDING')
    
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

class LeaveAttachment(BaseModel):
    REVIEW_STATUS_CHOICES = (
        ('PENDING', 'Pending Review'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    )

    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='attachments')
    file = models.FileField(upload_to='leave_attachments/')
    file_name = models.CharField(max_length=255)
    file_type = models.CharField(max_length=50, blank=True)
    file_size = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='uploaded_leave_attachments')
    review_status = models.CharField(max_length=20, choices=REVIEW_STATUS_CHOICES, default='PENDING')
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviewed_leave_attachments')
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewer_comments = models.TextField(blank=True)

    def __str__(self):
        return self.file_name

class LeaveWorkflow(BaseModel):
    name = models.CharField(max_length=100)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, null=True, blank=True, related_name='enterprise_workflows')
    department = models.ForeignKey('employees.Department', on_delete=models.CASCADE, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    escalation_enabled = models.BooleanField(default=False)
    auto_approval_enabled = models.BooleanField(default=False)

    def __str__(self):
        return self.name

class LeaveWorkflowStep(BaseModel):
    APPROVER_TYPE_CHOICES = (
        ('REPORTING_MANAGER', 'Reporting Manager'),
        ('DEPARTMENT_HEAD', 'Department Head'),
        ('HR', 'HR'),
        ('SPECIFIC_USER', 'Specific User'),
        ('ROLE', 'Role'),
        ('AUTO_APPROVE', 'Auto Approve'),
    )
    APPROVAL_MODE_CHOICES = (
        ('ANY_ONE', 'Any One'),
        ('ALL', 'All Approvers'),
    )

    workflow = models.ForeignKey(LeaveWorkflow, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveIntegerField()
    approver_type = models.CharField(max_length=30, choices=APPROVER_TYPE_CHOICES, default='REPORTING_MANAGER')
    specific_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    role_name = models.CharField(max_length=80, blank=True)
    approval_mode = models.CharField(max_length=20, choices=APPROVAL_MODE_CHOICES, default='ANY_ONE')
    sla_hours = models.PositiveIntegerField(default=24)
    escalate_to_type = models.CharField(max_length=30, choices=APPROVER_TYPE_CHOICES, blank=True)
    escalate_to_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='leave_escalation_steps')
    delegation_allowed = models.BooleanField(default=True)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"{self.workflow.name} step {self.order}"

class LeaveApproval(BaseModel):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('SKIPPED', 'Skipped'),
        ('ESCALATED', 'Escalated'),
        ('DELEGATED', 'Delegated'),
    )

    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='enterprise_approvals')
    workflow_step = models.ForeignKey(LeaveWorkflowStep, on_delete=models.SET_NULL, null=True, blank=True)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='leave_approvals')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    comments = models.TextField(blank=True)
    action_at = models.DateTimeField(null=True, blank=True)
    delegated_to = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='delegated_leave_approvals')

    class Meta:
        ordering = ['created_at']

class ApprovalWorkflow(BaseModel):
    """
    Supports multi-level approval chains (e.g., Manager -> Dept Head -> HR).
    """
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('SKIPPED', 'Skipped'),
    ]

    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='workflow_steps')
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    approver_role = models.CharField(max_length=50, blank=True, null=True)
    sequence_order = models.PositiveIntegerField()
    is_parallel = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    action_date = models.DateTimeField(null=True, blank=True)
    comments = models.TextField(blank=True)

    class Meta:
        ordering = ['sequence_order']

    def __str__(self):
        return f"Step {self.sequence_order} for {self.leave_request.id} ({self.status})"

class LeaveApprovalMatrix(BaseModel):
    """
    SaaS-ready template for approval chains.
    Allows HR to define if a 'SICK LEAVE' in 'SALES' needs TL -> HR approval.
    """
    name = models.CharField(max_length=100)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE, null=True, blank=True)
    department = models.ForeignKey('employees.Department', on_delete=models.CASCADE, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name

class LeaveApprovalMatrixStep(BaseModel):
    matrix = models.ForeignKey(LeaveApprovalMatrix, on_delete=models.CASCADE, related_name='steps')
    order = models.PositiveIntegerField()
    approver_role = models.CharField(max_length=50, choices=[
        ('MANAGER', 'Direct Manager'),
        ('DEPT_HEAD', 'Department Head'),
        ('HR', 'HR Manager'),
        ('ADMIN', 'Global Admin'),
    ])
    is_parallel = models.BooleanField(default=False, help_text="Anyone with this role can approve to move to next level")

    class Meta:
        ordering = ['order']


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
        ('LAPSED', 'Lapsed Leaves'),
    ])


    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

class HolidayCalendar(BaseModel):
    name = models.CharField(max_length=100)
    location_fk = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    branch = models.CharField(max_length=100, blank=True)
    year = models.PositiveIntegerField()
    is_default = models.BooleanField(default=False)

    class Meta:
        unique_together = ('organization', 'name', 'year')
        ordering = ['-year', 'name']

    def __str__(self):
        return f"{self.name} ({self.year})"

class Holiday(BaseModel):
    """
    Holiday calendar with regional granularity.
    """
    name = models.CharField(max_length=100)
    date = models.DateField()
    calendar = models.ForeignKey(HolidayCalendar, on_delete=models.CASCADE, null=True, blank=True, related_name='holidays')
    location_fk = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    holiday_type = models.CharField(max_length=20, choices=(
        ('NATIONAL', 'National'),
        ('REGIONAL', 'Regional'),
        ('COMPANY', 'Company'),
        ('OPTIONAL', 'Optional'),
    ), default='COMPANY')
    is_paid = models.BooleanField(default=True)
    is_optional = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} ({self.date})"

class LeaveEncashment(BaseModel):
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('APPROVED', 'Approved'),
        ('POSTED_TO_PAYROLL', 'Posted to Payroll'),
        ('CANCELLED', 'Cancelled'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_encashments')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    days = models.DecimalField(max_digits=6, decimal_places=2)
    rate_per_day = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    gross_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    taxable_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    payroll_run = models.ForeignKey('payroll.PayrollRun', on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')

    def __str__(self):
        return f"{self.employee} {self.leave_type.code} encashment {self.days}"

class LeaveCarryForwardLog(BaseModel):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    from_year = models.PositiveIntegerField()
    to_year = models.PositiveIntegerField()
    eligible_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    carried_forward_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    expired_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    encashed_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    processed_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.employee} {self.leave_type.code} {self.from_year}->{self.to_year}"

class LeaveAttendanceEvent(BaseModel):
    SYNC_STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('SYNCED', 'Synced'),
        ('FAILED', 'Failed'),
        ('REVERSED', 'Reversed'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_attendance_events')
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='attendance_events')
    date = models.DateField()
    session_type = models.CharField(max_length=20, default='FULL')
    paid_status = models.CharField(max_length=20, default='PAID')
    sync_status = models.CharField(max_length=20, choices=SYNC_STATUS_CHOICES, default='PENDING')
    sync_message = models.TextField(blank=True)

    class Meta:
        unique_together = ('leave_request', 'date', 'session_type')
        indexes = [
            models.Index(fields=['employee', 'date', 'sync_status']),
        ]

class LeavePayrollImpact(BaseModel):
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('POSTED', 'Posted'),
        ('ADJUSTED', 'Adjusted'),
        ('REVERSED', 'Reversed'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_payroll_impacts')
    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.SET_NULL, null=True, blank=True, related_name='payroll_impacts')
    payroll_run = models.ForeignKey('payroll.PayrollRun', on_delete=models.SET_NULL, null=True, blank=True)
    month = models.PositiveSmallIntegerField()
    year = models.PositiveIntegerField()
    paid_leave_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    lop_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    encashment_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    encashment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    adjustment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    class Meta:
        indexes = [
            models.Index(fields=['employee', 'month', 'year', 'status']),
        ]

class LeaveAuditLog(BaseModel):
    entity_type = models.CharField(max_length=80)
    entity_id = models.CharField(max_length=80)
    action = models.CharField(max_length=80)
    old_value = models.JSONField(default=dict, blank=True)
    new_value = models.JSONField(default=dict, blank=True)
    performed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='leave_audit_actions')
    performed_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    class Meta:
        ordering = ['-performed_at']
        indexes = [
            models.Index(fields=['entity_type', 'entity_id']),
            models.Index(fields=['action', 'performed_at']),
        ]

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

class RestrictedHolidayClaim(BaseModel):
    """
    Tracks which optional holidays an employee has chosen to take.
    """
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='rh_claims')
    holiday = models.ForeignKey(Holiday, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    claimed_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=(
        ('PENDING', 'Pending Approval'),  
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    ), default='APPROVED') # Usually RH is auto-approved or pre-approved by policy

    class Meta:
        unique_together = ('employee', 'holiday')
        ordering = ['holiday__date']

    def __str__(self):
        return f"{self.employee.first_name} - RH: {self.holiday.name}"
