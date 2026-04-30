from django.db import models
from django.conf import settings

# Create your models here.

class TenantQuerySet(models.QuerySet):
    def for_tenant(self, organization):
        return self.filter(organization=organization)

    def active(self):
        return self.filter(is_deleted=False, is_active=True)

class TenantManager(models.Manager):
    def get_queryset(self):
        # By default, exclude deleted records for industry-standard soft-delete
        return TenantQuerySet(self.model, using=self._db).filter(is_deleted=False)

class BaseModel(models.Model):

    """
    Abstract base model for SaaS multi-tenancy, audit tracking, and soft-delete.
    """
    organization = models.ForeignKey(
        'accounts.Organization', 
        on_delete=models.CASCADE,
        related_name='%(class)s_records',
        null=True, blank=True,
        db_index=True # Crucial for SaaS performance
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True, db_index=True)
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = TenantManager()
    all_objects = models.Manager() # Standard manager for bypass if needed



    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_created'
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_updated'
    )

    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='%(class)s_deleted'
    )

    class Meta:
        abstract = True

class Department(BaseModel):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    class Meta:
        unique_together = ('organization', 'name')


    def __str__(self):
        return self.name

class Designation(BaseModel):
    name = models.CharField(max_length=100)

    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name

class Employee(BaseModel):
    # Basic Info
    employee_id = models.CharField(max_length=20)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)

    email = models.EmailField()

    phone_number = models.CharField(max_length=15)

    # Personal Info
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(
        max_length=10, 
        choices=[('Male', 'Male'), ('Female', 'Female'), ('Other', 'Other')],
        blank=True, 
        null=True
    )
    marital_status = models.CharField(
        max_length=10, 
        choices=[('Single', 'Single'), ('Married', 'Married'), ('Divorced', 'Divorced'), ('Widowed', 'Widowed')],
        blank=True, 
        null=True
    )
    blood_group = models.CharField(
        max_length=5, 
        choices=[('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'), ('AB+', 'AB+'), ('AB-', 'AB-'), ('O+', 'O+'), ('O-', 'O-')],
        blank=True, 
        null=True
    )
    nationality = models.CharField(max_length=50, blank=True, null=True, default='Indian')

    # Current Address
    current_address = models.TextField()
    current_city = models.CharField(max_length=50, blank=True, null=True)
    current_state = models.CharField(max_length=50, blank=True, null=True)
    current_country = models.CharField(max_length=50, blank=True, null=True, default='India')
    current_pincode = models.CharField(max_length=6, blank=True, null=True)

    # Permanent Address
    permanent_address = models.TextField()
    permanent_city = models.CharField(max_length=50, blank=True, null=True)
    permanent_state = models.CharField(max_length=50, blank=True, null=True)
    permanent_country = models.CharField(max_length=50, blank=True, null=True, default='India')
    permanent_pincode = models.CharField(max_length=6, blank=True, null=True)
    
    # Work Info
    joining_date = models.DateField(blank=True, null=True)
    employment_type = models.CharField(
        max_length=20, 
        choices=[
            ('Full Time', 'Full Time'), 
            ('Part Time', 'Part Time'), 
            ('Contract', 'Contract'), 
            ('Temporary', 'Temporary')
        ],
        blank=True,
        null=True
    )
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True)
    designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, blank=True)
    manager = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subordinates')

    # Company Details
    work_location = models.CharField(max_length=100, blank=True, null=True)
    
    # Financial Info
    pan_number = models.CharField(max_length=10, blank=True)
    aadhaar_number = models.CharField(max_length=12, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    bank_account_number = models.CharField(max_length=20, blank=True)
    ifsc_code = models.CharField(max_length=20, blank=True)

    # Emergency Contact
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_number = models.CharField(max_length=15, blank=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True)

    # Documents
    resume = models.FileField(upload_to='resumes/', blank=True)
    offer_letter = models.FileField(upload_to='offer_letters/', blank=True)
    aadhaar_card = models.FileField(upload_to='aadhaar_cards/', blank=True)
    pan_card = models.FileField(upload_to='pan_cards/', blank=True)
    appointment_letter = models.FileField(upload_to='appointment_letters/', blank=True)
    
    # System
    profile_img = models.ImageField(upload_to='profile_imgs/', blank=True)

    def __str__(self):
        return f"{self.employee_id} - {self.first_name} {self.last_name}"

    class Meta:
        unique_together = (('organization', 'employee_id'), ('organization', 'email'))
        indexes = [
            models.Index(fields=['organization', 'employee_id']),
            models.Index(fields=['organization', 'email']),
        ]

