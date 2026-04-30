from django.db import models
from employees.models import BaseModel, Employee

class SalaryComponent(BaseModel):
    """
    Defines various components like Basic, HRA, PF, etc.
    """
    COMPONENT_TYPES = (
        ('EARNING', 'Earning'),
        ('DEDUCTION', 'Deduction'),
    )
    name = models.CharField(max_length=100)
    component_type = models.CharField(max_length=20, choices=COMPONENT_TYPES)
    is_taxable = models.BooleanField(default=True)
    is_calculated_on_attendance = models.BooleanField(default=True)
    
    def __str__(self):
        return f"{self.name} ({self.get_component_type_display()})"

class SalaryStructure(BaseModel):
    """
    A template of salary components (e.g., 'Executive Structure', 'Intern Structure').
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    
    def __str__(self):
        return self.name

class SalaryStructureComponent(BaseModel):
    """
    Maps components to a structure with specific values or percentages.
    """
    structure = models.ForeignKey(SalaryStructure, on_delete=models.CASCADE, related_name='components')
    component = models.ForeignKey(SalaryComponent, on_delete=models.CASCADE)
    percentage_of_basic = models.DecimalField(
        max_digits=5, decimal_places=2, default=0.0, 
        help_text="Set a percentage if this is calculated based on basic pay."
    )
    fixed_amount = models.DecimalField(
        max_digits=12, decimal_places=2, default=0.0,
        help_text="Set a fixed amount if this is not percentage-based."
    )

    def __str__(self):
        return f"{self.structure.name} - {self.component.name}"

class EmployeeSalary(BaseModel):
    """
    The actual salary configuration for an individual employee.
    """
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='salary_config')
    structure = models.ForeignKey(SalaryStructure, on_delete=models.PROTECT)
    base_salary = models.DecimalField(max_digits=12, decimal_places=2, help_text="The total CTC or monthly gross base.")
    
    def __str__(self):
        return f"{self.employee.first_name} - {self.base_salary}"

class Payslip(BaseModel):
    """
    Monthly generated record of payment.
    """
    MONTH_CHOICES = (
        (1, 'January'), (2, 'February'), (3, 'March'), (4, 'April'),
        (5, 'May'), (6, 'June'), (7, 'July'), (8, 'August'),
        (9, 'September'), (10, 'October'), (11, 'November'), (12, 'December'),
    )
    STATUS_CHOICES = (
        ('DRAFT', 'Draft'),
        ('GENERATED', 'Generated'),
        ('PAID', 'Paid'),
        ('CANCELLED', 'Cancelled'),
    )
    
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payslips')
    month = models.PositiveIntegerField(choices=MONTH_CHOICES)
    year = models.PositiveIntegerField()
    
    # Summary of financials
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2)
    net_salary = models.DecimalField(max_digits=12, decimal_places=2)
    
    # Detailed attendance metrics for calculation audit
    total_days = models.PositiveIntegerField()
    payable_days = models.DecimalField(max_digits=4, decimal_places=2)
    absent_days = models.DecimalField(max_digits=4, decimal_places=2)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='DRAFT')
    payment_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, blank=True)
    transaction_id = models.CharField(max_length=100, blank=True)
    
    remarks = models.TextField(blank=True)
    
    class Meta:
        unique_together = ('employee', 'month', 'year')

    def __str__(self):
        return f"{self.employee.first_name} - {self.month}/{self.year}"
