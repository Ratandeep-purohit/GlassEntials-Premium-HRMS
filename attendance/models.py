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
        from django.db.models import Q
        
        qs = ShiftAssignment.objects.filter(employee=self.employee).exclude(pk=self.pk)
        
        if self.effective_to:
            overlaps = qs.filter(
                Q(effective_to__isnull=True, effective_from__lte=self.effective_to) |
                Q(effective_to__isnull=False, effective_from__lte=self.effective_to, effective_to__gte=self.effective_from)
            )
        else:
            overlaps = qs.filter(
                Q(effective_to__isnull=True) |
                Q(effective_to__isnull=False, effective_to__gte=self.effective_from)
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
    early_out_minutes=models.PositiveIntegerField(default=0)
    reason=models.TextField(blank=True)
    overtime_hours=models.DecimalField(max_digits=5,decimal_places=2,default=0.0)
    total_break_minutes=models.PositiveIntegerField(default=0)
    net_work_hours=models.DecimalField(max_digits=5,decimal_places=2,null=True,blank=True)
    remarks=models.TextField(blank=True)
    
    @property
    def current_work_time(self):
        import datetime
        
        if not self.clock_in:
            return "--"
            
        t1 = datetime.datetime.combine(self.date, self.clock_in)
        if self.clock_out:
            t2 = datetime.datetime.combine(self.date, self.clock_out)
        else:
            if self.date == datetime.date.today():
                t2 = datetime.datetime.now()
            else:
                return "-- (Missed Clock Out)"
            
        delta = t2 - t1
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 0:
            return "0h 0m"
            
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        
        return f"{hours}h {minutes}m"

    @property
    def formatted_late_time(self):
        if self.late_minutes == 0:
            return ""
        hours = self.late_minutes // 60
        mins = self.late_minutes % 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    @property
    def formatted_early_out_time(self):
        if self.early_out_minutes == 0:
            return ""
        hours = self.early_out_minutes // 60
        mins = self.early_out_minutes % 60
        if hours > 0:
            return f"{hours}h {mins}m"
        return f"{mins}m"

    def __str__(self):
        return f"{self.employee} - {self.date}"

class AttendanceCorrection(BaseModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]
    attendance = models.ForeignKey(Attendance, on_delete=models.CASCADE, related_name='corrections')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendance_corrections')
    requested_clock_in = models.TimeField(null=True, blank=True)
    requested_clock_out = models.TimeField(null=True, blank=True)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    resolved_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_corrections')
    resolved_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Correction for {self.employee} on {self.attendance.date}"

class BreakLog(BaseModel):
    attendance = models.ForeignKey(Attendance, on_delete=models.CASCADE, related_name='breaks')
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(default=0)
    
    def __str__(self):
        return f"Break for {self.attendance.employee} on {self.attendance.date}"

class OvertimeRequest(BaseModel):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('APPROVED', 'Approved'),
        ('REJECTED', 'Rejected'),
    ]
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='overtime_requests')
    date = models.DateField()
    hours_requested = models.DecimalField(max_digits=4, decimal_places=2)
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    approved_by = models.ForeignKey('accounts.CustomUser', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_overtimes')
    
    def __str__(self):
        return f"Overtime {self.hours_requested}h for {self.employee} on {self.date}"
