from django.db import models
from django.utils import timezone
import os
import uuid

from employees.models import BaseModel


def announcement_image_path(instance, filename):
    """Store images under announcements/<org_id>/<announcement_id>/<uuid>.<ext>"""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    safe_ext = ext if ext in ('jpg', 'jpeg', 'png', 'webp', 'gif') else 'jpg'
    unique_name = f"{uuid.uuid4().hex}.{safe_ext}"
    org_id = instance.announcement.organization_id or 'unknown'
    ann_id = instance.announcement_id or 'new'
    return os.path.join('announcements', str(org_id), str(ann_id), unique_name)


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

    @property
    def images_list(self):
        return self.images.order_by('display_order', 'created_at')


class AnnouncementImage(models.Model):
    """Stores images attached to an Announcement. Strictly org-scoped via the parent Announcement FK."""
    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name='images',
    )
    image = models.ImageField(upload_to=announcement_image_path)
    original_filename = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'created_at']

    def __str__(self):
        return f"Image for '{self.announcement.title}' (#{self.pk})"
