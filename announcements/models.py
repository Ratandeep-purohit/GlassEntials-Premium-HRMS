from django.db import models
from django.utils import timezone

from employees.models import BaseModel


class Announcement(BaseModel):
    CATEGORY_CHOICES = [
        ('COMPANY_NEWS', 'Company News'),
        ('POLICY', 'Policy'),
        ('EVENT', 'Event'),
        ('HR_UPDATE', 'HR Update'),
        ('OPERATIONS', 'Operations'),
    ]

    AUDIENCE_CHOICES = [
        ('ALL', 'All Employees'),
        ('EMPLOYEES', 'Employees Only'),
        ('STAFF', 'Staff Only'),
    ]

    title = models.CharField(max_length=180)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default='COMPANY_NEWS')
    audience = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default='ALL')
    department = models.CharField(max_length=80, default='HR Department')
    summary = models.TextField(blank=True)
    body = models.TextField()
    is_pinned = models.BooleanField(default=False, db_index=True)
    publish_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-is_pinned', '-publish_at', '-created_at']
        indexes = [
            models.Index(fields=['organization', 'is_active', 'is_deleted', 'publish_at']),
            models.Index(fields=['organization', 'audience', 'category']),
        ]

    def __str__(self):
        return self.title

    @property
    def is_visible_now(self):
        now = timezone.now()
        if not self.is_active or self.is_deleted or self.publish_at > now:
            return False
        return not self.expires_at or self.expires_at >= now

