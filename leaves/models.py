from django.db import models
from employees.models import BaseModel, Employee

class LeaveType(BaseModel):
    """
    Defines types of leaves available in the organization (e.g., SL, CL, EL).
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10)
    description = models.TextField(blank=True)
    is_paid = models.BooleanField(default=True)
    total_days_per_year = models.PositiveIntegerField(default=12)
    carry_forward_limit = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"{self.name} ({self.code})"

class LeaveRequest(BaseModel):
    """
    Individual leave applications from employees.
    """
    STATUS_CHOICES = (
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    )
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    approved_by = models.ForeignKey(
        'accounts.CustomUser', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        related_name='approved_leaves'
    )
    approval_date = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    
    total_days = models.DecimalField(max_digits=4, decimal_places=1, help_text="Number of working days of leave.")
    
    def __str__(self):
        return f"{self.employee.first_name} - {self.leave_type.code} ({self.start_date} to {self.end_date})"

class Holiday(BaseModel):
    """
    Public or optional holidays specific to an organization.
    """
    name = models.CharField(max_length=100)
    date = models.DateField()
    is_optional = models.BooleanField(default=False)
    
    def __str__(self):
        return f"{self.name} - {self.date}"
