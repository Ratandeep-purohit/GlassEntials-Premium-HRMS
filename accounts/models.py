from django.db import models
from django.contrib.auth.models import AbstractUser


class Organization(models.Model):
    name = models.CharField(max_length=200)
    unique_code = models.CharField(max_length=50, unique=True)

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    phone = models.CharField(max_length=15, blank=True, null=True)
    organization = models.ForeignKey(
        Organization,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    is_approved = models.BooleanField(default=False)
    must_change_password = models.BooleanField(
        default=False,
        help_text="If True, user must create a new password before accessing the system.",
    )

    def __str__(self):
        return self.username
