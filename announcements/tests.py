from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Organization
from .models import Announcement


User = get_user_model()


class AnnouncementModuleTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="GlassEntials", unique_code="GE001")
        self.other_org = Organization.objects.create(name="Other Org", unique_code="OO001")
        self.admin = User.objects.create_user(
            username="admin",
            email="admin@example.com",
            password="password123",
            is_staff=True,
            is_approved=True,
            organization=self.org,
        )
        self.employee = User.objects.create_user(
            username="employee",
            email="employee@example.com",
            password="password123",
            is_approved=True,
            organization=self.org,
        )
        self.other_employee = User.objects.create_user(
            username="other",
            email="other@example.com",
            password="password123",
            is_approved=True,
            organization=self.other_org,
        )

    def test_admin_can_create_announcement(self):
        client = Client()
        client.login(username="admin", password="password123")

        response = client.post(reverse("announcements:manage"), {
            "title": "New Safety Policy",
            "category": "POLICY",
            "audience": "ALL",
            "department": "HR Department",
            "body": "Please review the updated workplace safety policy.",
            "is_active": "on",
        })

        self.assertRedirects(response, reverse("announcements:manage"))
        self.assertTrue(Announcement.objects.filter(
            organization=self.org,
            title="New Safety Policy",
        ).exists())

    def test_employee_can_view_visible_announcement(self):
        announcement = Announcement.objects.create(
            organization=self.org,
            title="Team Offsite",
            category="EVENT",
            audience="ALL",
            body="Save the date.",
        )
        client = Client()
        client.login(username="employee", password="password123")

        response = client.get(reverse("announcements:list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, announcement.title)

    def test_announcements_are_tenant_scoped(self):
        Announcement.objects.create(
            organization=self.other_org,
            title="Other Org Update",
            category="COMPANY_NEWS",
            audience="ALL",
            body="Private update.",
        )
        client = Client()
        client.login(username="employee", password="password123")

        response = client.get(reverse("announcements:list"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "Other Org Update")

