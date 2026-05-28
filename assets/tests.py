from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Organization
from employees.models import Employee
from .models import AssetCategory, Asset, AssetAssignment, AssetRequest
from datetime import date, timedelta
from django.contrib.messages import get_messages

User = get_user_model()

class AssetModuleTests(TestCase):
    def setUp(self):
        # Create organization
        self.org = Organization.objects.create(name="Glassentials Org")
        
        # Create users
        self.admin_user = User.objects.create_user(
            username="admin_user", email="admin@glassentials.com", password="password123",
            is_staff=True, organization=self.org
        )
        self.emp_user = User.objects.create_user(
            username="emp_user", email="employee@glassentials.com", password="password123",
            is_staff=False, organization=self.org
        )
        
        # Create employee record
        self.employee = Employee.objects.create(
            organization=self.org,
            employee_id="GEMP001",
            first_name="Jane",
            last_name="Doe",
            email="employee@glassentials.com",
            phone_number="9876543210",
            is_active=True
        )
        
        # Setup clients
        self.admin_client = Client()
        self.admin_client.login(username="admin_user", password="password123")
        
        self.emp_client = Client()
        self.emp_client.login(username="emp_user", password="password123")

    def test_manage_categories_view(self):
        # 1. Create a category
        response = self.admin_client.post(reverse('assets:manage_categories'), {
            'name': 'Laptop',
            'icon': 'fa-laptop'
        })
        self.assertRedirects(response, reverse('assets:manage_categories'))
        
        # Verify created
        cat = AssetCategory.objects.get(organization=self.org, name='Laptop')
        self.assertEqual(cat.icon, 'fa-laptop')
        
        # 2. Try to create duplicate category (should show error, no crash)
        response = self.admin_client.post(reverse('assets:manage_categories'), {
            'name': 'Laptop',
            'icon': 'fa-box'
        })
        self.assertRedirects(response, reverse('assets:manage_categories'))
        
        # Verify error message in redirect
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("Category 'Laptop' already exists." in str(m) for m in messages))
        
        # 3. Soft-delete the category
        cat.is_deleted = True
        cat.save()
        
        # 4. Re-create the soft-deleted category (should restore it)
        response = self.admin_client.post(reverse('assets:manage_categories'), {
            'name': 'Laptop',
            'icon': 'fa-laptop-code'
        })
        self.assertRedirects(response, reverse('assets:manage_categories'))
        
        cat.refresh_from_db()
        self.assertFalse(cat.is_deleted)
        self.assertEqual(cat.icon, 'fa-laptop-code')
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("Category 'Laptop' has been restored." in str(m) for m in messages))

        # 5. Edit the category
        response = self.admin_client.post(reverse('assets:edit_category', args=[cat.id]), {
            'name': 'Workstation Laptop',
            'icon': 'fa-laptop'
        })
        self.assertRedirects(response, reverse('assets:manage_categories'))
        cat.refresh_from_db()
        self.assertEqual(cat.name, 'Workstation Laptop')
        self.assertEqual(cat.icon, 'fa-laptop')

        # 6. Soft-delete from the management page
        response = self.admin_client.post(reverse('assets:delete_category', args=[cat.id]))
        self.assertRedirects(response, reverse('assets:manage_categories'))
        cat = AssetCategory.all_objects.get(id=cat.id)
        self.assertTrue(cat.is_deleted)
        self.assertFalse(cat.is_active)
        self.assertIsNotNone(cat.deleted_at)

    def test_add_asset_view(self):
        # Create category
        cat = AssetCategory.objects.create(organization=self.org, name="Furniture", icon="fa-chair")
        
        # 1. Add valid asset
        data = {
            'name': 'Ergonomic Chair',
            'asset_code': 'FUR-001',
            'category_id': cat.id,
            'serial_number': '12345',
            'brand': 'Steelcase',
            'model_number': 'Gesture',
            'condition': 'GOOD',
            'location': 'Main Office'
        }
        response = self.admin_client.post(reverse('assets:add_asset'), data)
        self.assertRedirects(response, reverse('assets:inventory'))
        
        # Verify created
        asset = Asset.objects.get(organization=self.org, asset_code='FUR-001')
        self.assertEqual(asset.name, 'Ergonomic Chair')
        
        # 2. Try to add duplicate asset code (should show error, no crash, and repopulate form)
        data_dup = {
            'name': 'Another Chair',
            'asset_code': 'FUR-001',
            'category_id': cat.id,
            'serial_number': '99999',
            'brand': 'Steelcase',
            'model_number': 'Leap',
            'condition': 'EXCELLENT',
            'location': 'Conference Room'
        }
        response = self.admin_client.post(reverse('assets:add_asset'), data_dup)
        self.assertEqual(response.status_code, 200) # Renders form back with errors
        
        # Verify error message and form repopulation
        messages = list(get_messages(response.wsgi_request))
        self.assertTrue(any("An active asset with code 'FUR-001' already exists." in str(m) for m in messages))
        self.assertEqual(response.context['asset']['name'], 'Another Chair')
        self.assertEqual(response.context['asset']['model_number'], 'Leap')

    def test_edit_asset_view(self):
        cat = AssetCategory.objects.create(organization=self.org, name="Monitors", icon="fa-desktop")
        asset = Asset.objects.create(
            organization=self.org,
            category=cat,
            name="UltraWide Monitor",
            asset_code="MON-001",
            condition="EXCELLENT",
            status="AVAILABLE"
        )
        
        # Edit asset
        data = {
            'name': 'Super UltraWide Monitor',
            'category_id': cat.id,
            'serial_number': 'SN-MON-99',
            'brand': 'Dell',
            'model_number': 'U4919DW',
            'condition': 'GOOD',
            'status': 'AVAILABLE',
            'location': 'Design Lab'
        }
        response = self.admin_client.post(reverse('assets:edit_asset', args=[asset.id]), data)
        self.assertRedirects(response, reverse('assets:inventory'))
        
        asset.refresh_from_db()
        self.assertEqual(asset.name, 'Super UltraWide Monitor')
        self.assertEqual(asset.brand, 'Dell')

    def test_assign_and_return_asset(self):
        cat = AssetCategory.objects.create(organization=self.org, name="Laptops", icon="fa-laptop")
        asset = Asset.objects.create(
            organization=self.org,
            category=cat,
            name="ThinkPad T14",
            asset_code="LAP-002",
            status="AVAILABLE"
        )
        
        # 1. Assign asset
        data = {
            'employee_id': self.employee.id,
            'condition_at_issue': 'GOOD',
            'expected_return_date': (date.today() + timedelta(days=180)).strftime('%Y-%m-%d')
        }
        response = self.admin_client.post(reverse('assets:assign_asset', args=[asset.id]), data)
        self.assertRedirects(response, reverse('assets:inventory'))
        
        asset.refresh_from_db()
        self.assertEqual(asset.status, 'ASSIGNED')
        
        assignment = AssetAssignment.objects.get(asset=asset, employee=self.employee, status='ACTIVE')
        self.assertIsNotNone(assignment)
        
        # 2. Return asset
        data_return = {
            'condition_at_return': 'GOOD',
            'new_status': 'AVAILABLE'
        }
        response = self.admin_client.post(reverse('assets:return_asset', args=[assignment.id]), data_return)
        self.assertRedirects(response, reverse('assets:inventory'))
        
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, 'RETURNED')
        
        asset.refresh_from_db()
        self.assertEqual(asset.status, 'AVAILABLE')

    def test_request_asset_view(self):
        cat = AssetCategory.objects.create(organization=self.org, name="Headphones", icon="fa-headphones")
        
        # 1. Request asset as employee
        data = {
            'category_id': cat.id,
            'priority': 'HIGH',
            'reason': 'Need headphones for clients calls'
        }
        response = self.emp_client.post(reverse('assets:request_asset'), data)
        self.assertRedirects(response, reverse('assets:my_assets'))
        
        req = AssetRequest.objects.get(employee=self.employee, category=cat)
        self.assertEqual(req.priority, 'HIGH')
        self.assertEqual(req.status, 'PENDING')
        
        # 2. Check warning/redirect on duplicate pending request
        response2 = self.emp_client.post(reverse('assets:request_asset'), data)
        self.assertRedirects(response2, reverse('assets:my_assets'))
        messages = list(get_messages(response2.wsgi_request))
        self.assertTrue(any("You already have a pending request for a 'Headphones'." in str(m) for m in messages))
