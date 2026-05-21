from django.db import models
from employees.models import BaseModel, Employee
from django.conf import settings


class AssetCategory(BaseModel):
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50, default='fa-box', help_text='Font Awesome icon class e.g. fa-laptop')
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = 'Asset Categories'
        unique_together = ('organization', 'name')

    def __str__(self):
        return self.name


class Asset(BaseModel):
    CONDITION_CHOICES = [
        ('EXCELLENT', 'Excellent'),
        ('GOOD', 'Good'),
        ('FAIR', 'Fair'),
        ('POOR', 'Poor'),
    ]
    STATUS_CHOICES = [
        ('AVAILABLE', 'Available'),
        ('ASSIGNED', 'Assigned'),
        ('MAINTENANCE', 'Under Maintenance'),
        ('RETIRED', 'Retired'),
    ]

    category = models.ForeignKey(AssetCategory, on_delete=models.SET_NULL, null=True, related_name='assets')
    name = models.CharField(max_length=200)
    asset_code = models.CharField(max_length=50, unique=True, help_text='Unique identifier e.g. LAP-001')
    serial_number = models.CharField(max_length=100, blank=True)
    brand = models.CharField(max_length=100, blank=True)
    model_number = models.CharField(max_length=100, blank=True)
    purchase_date = models.DateField(null=True, blank=True)
    purchase_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    condition = models.CharField(max_length=20, choices=CONDITION_CHOICES, default='GOOD')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='AVAILABLE')
    location = models.CharField(max_length=100, blank=True, help_text='Physical location / store room')
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.asset_code} — {self.name}"

    @property
    def current_assignment(self):
        return self.assignments.filter(status='ACTIVE').first()


class AssetAssignment(BaseModel):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('RETURNED', 'Returned'),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='assignments')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='asset_assignments')
    assigned_date = models.DateField()
    expected_return_date = models.DateField(null=True, blank=True)
    returned_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    condition_at_issue = models.CharField(max_length=20, choices=Asset.CONDITION_CHOICES, default='GOOD')
    condition_at_return = models.CharField(max_length=20, choices=Asset.CONDITION_CHOICES, null=True, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"{self.asset.asset_code} → {self.employee.first_name} ({self.status})"


class AssetRequest(BaseModel):
    PRIORITY_CHOICES = [
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
    ]
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
        ('FULFILLED', 'Fulfilled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='asset_requests')
    category = models.ForeignKey(AssetCategory, on_delete=models.SET_NULL, null=True, related_name='requests')
    reason = models.TextField()
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_asset_requests'
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    fulfillment_asset = models.ForeignKey(
        Asset, on_delete=models.SET_NULL, null=True, blank=True, related_name='fulfillment_requests'
    )
    rejection_reason = models.TextField(blank=True)

    def __str__(self):
        return f"{self.employee.first_name} — {self.category} ({self.status})"
