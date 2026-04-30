from django.db import models
from employees.models import BaseModel, Employee

# Create your models here.
class Shift(BaseModel):
    name = models.CharField(max_length=100)

    start_time = models.TimeField()
    end_time = models.TimeField()

    grace_minutes=models.PositiveIntegerField(default=0)
    minimum_half_day_hours=models.DecimalField(max_digits=5,decimal_places=2,default=4.0)
    minimum_full_day_hours=models.DecimalField(max_digits=5,decimal_places=2,default=8.0)
    is_night_shift=models.BooleanField(default=False)

    def __str__(self):
        return self.name
class ShiftAssignment(BaseModel):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_assignments')
    shift = models.ForeignKey(Shift, on_delete=models.CASCADE, related_name='assignments')
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.employee} - {self.shift} ({self.effective_from} to {self.effective_to or 'Present'})"

    def clean(self):
        from django.core.exceptions import ValidationError
        
        qs = ShiftAssignment.objects.filter(employee=self.employee).exclude(pk=self.pk)
        
        if self.effective_to:
            overlaps = qs.filter(
                models.Q(effective_to__isnull=True, effective_from__lte=self.effective_to) |
                models.Q(effective_to__isnull=False, effective_from__lte=self.effective_to, effective_to__gte=self.effective_from)
            )
        else:
            overlaps = qs.filter(
                models.Q(effective_to__isnull=True) |
                models.Q(effective_to__isnull=False, effective_to__gte=self.effective_from)
            )

        if overlaps.exists():
            raise ValidationError(f"Shift overlap detected for {self.employee}. This employee is already assigned to a shift during this period.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class AttendanceStatus(BaseModel):
    name = models.CharField(max_length=50)
    code = models.CharField(max_length=10)
    is_paid = models.BooleanField(default=True)
    payable_day_value = models.DecimalField(max_digits=3, decimal_places=2, default=1.0)
    is_attendance_counted = models.BooleanField(default=True)
    color_code = models.CharField(max_length=7, blank=True)  # Hex color
    
    class Meta:
        verbose_name_plural = 'Attendance Statuses'

    def __str__(self):
        return f"{self.name} ({self.code})"
    
class Attendance(BaseModel):
    employee=models.ForeignKey(Employee,on_delete=models.CASCADE,related_name='attendances')
    date=models.DateField()
    shift=models.ForeignKey(Shift,on_delete=models.SET_NULL,null=True,blank=True)
    status=models.ForeignKey(AttendanceStatus,on_delete=models.SET_NULL,null=True,blank=True)
    clock_in=models.TimeField(null=True,blank=True)
    clock_out=models.TimeField(null=True,blank=True)
    total_work_hours=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    late_minutes=models.PositiveIntegerField(default=0)
    reason=models.TextField(blank=True)
    overtime_hours=models.DecimalField(max_digits=5,decimal_places=2,default=0.0)
    remarks=models.TextField(blank=True)
    def __str__(self):
        return f"{self.employee} - {self.date}"
