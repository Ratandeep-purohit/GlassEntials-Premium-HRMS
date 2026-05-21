from django.db import models
from django.conf import settings
from accounts.models import Organization

class Notification(models.Model):
    TYPES = (
        ('LEAVE', 'Leave Update'),
        ('ATTENDANCE', 'Attendance Update'),
        ('SYSTEM', 'System Alert'),
        ('LOAN', 'Loan Update'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    organization = models.ForeignKey('accounts.Organization', on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=TYPES, default='SYSTEM')
    link = models.CharField(max_length=255, blank=True, null=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.title}"
