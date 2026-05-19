from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Organization
from employees.models import Employee
from payroll.models import Arrear, SalaryComponent

User = get_user_model()

class ArrearsTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        
        # Create users
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@test.com", password="password123",
            is_staff=True, organization=self.org
        )
        self.emp_user = User.objects.create_user(
            username="employee", email="emp@test.com", password="password123",
            is_staff=False, organization=self.org
        )
        
        # Create employee record
        self.employee = Employee.objects.create(
            organization=self.org,
            employee_id="EMP001",
            first_name="John",
            last_name="Doe",
            email="emp@test.com",
            phone_number="1234567890",
            is_active=True
        )
        
        # Create component
        self.component = SalaryComponent.objects.create(
            organization=self.org,
            code="BONUS",
            name="Bonus Component",
            component_type=SalaryComponent.ComponentType.EARNING,
            calculation_type=SalaryComponent.CalculationType.FIXED
        )
        
        # Clients
        self.admin_client = Client()
        self.admin_client.login(username="admin", password="password123")
        
        self.emp_client = Client()
        self.emp_client.login(username="employee", password="password123")

    def test_admin_view_requires_staff(self):
        # Admin can access admin_arrears
        response = self.admin_client.get(reverse('admin_arrears'))
        self.assertEqual(response.status_code, 200)
        
        # Regular employee is redirected
        response = self.emp_client.get(reverse('admin_arrears'))
        self.assertRedirects(response, reverse('my_arrears'))

    def test_admin_create_arrear_success(self):
        # Create arrear via POST
        data = {
            'employee': self.employee.id,
            'component': self.component.id,
            'arrear_type': 'EARNING',
            'from_month': 1,
            'from_year': 2026,
            'to_month': 2,
            'to_year': 2026,
            'amount': '500.00',
            'reason': 'Performance bonus correction'
        }
        response = self.admin_client.post(reverse('admin_arrears'), data)
        self.assertRedirects(response, reverse('admin_arrears'))
        
        # Verify DB record
        arrear = Arrear.objects.filter(employee=self.employee).first()
        self.assertIsNotNone(arrear)
        self.assertEqual(arrear.amount, Decimal('500.00'))
        self.assertEqual(arrear.reason, 'Performance bonus correction')
        self.assertEqual(arrear.status, Arrear.ArrearStatus.PENDING)

    def test_admin_create_arrear_validation_failure(self):
        # Amount <= 0 should fail validation
        data = {
            'employee': self.employee.id,
            'component': self.component.id,
            'arrear_type': 'EARNING',
            'from_month': 1,
            'from_year': 2026,
            'to_month': 2,
            'to_year': 2026,
            'amount': '-10.00',
            'reason': 'Invalid amount'
        }
        # Post request
        response = self.admin_client.post(reverse('admin_arrears'), data)
        self.assertRedirects(response, reverse('admin_arrears'))
        # Database should still be empty
        self.assertEqual(Arrear.objects.count(), 0)

    def test_admin_cancel_arrear(self):
        # Create an arrear
        arrear = Arrear.objects.create(
            organization=self.org,
            employee=self.employee,
            component=self.component,
            arrear_type=Arrear.ArrearType.EARNING,
            from_month=1,
            from_year=2026,
            to_month=1,
            to_year=2026,
            amount=Decimal('100.00'),
            reason='Temp correction'
        )
        
        # Cancel it
        response = self.admin_client.get(reverse('admin_cancel_arrear', args=[arrear.id]))
        self.assertRedirects(response, reverse('admin_arrears'))
        
        arrear.refresh_from_db()
        self.assertEqual(arrear.status, Arrear.ArrearStatus.CANCELLED)

    def test_employee_my_arrears_math(self):
        # Create pending earning
        Arrear.objects.create(
            organization=self.org,
            employee=self.employee,
            component=self.component,
            arrear_type=Arrear.ArrearType.EARNING,
            from_month=1,
            from_year=2026,
            to_month=1,
            to_year=2026,
            amount=Decimal('150.00'),
            reason='Earning'
        )
        # Create pending deduction
        Arrear.objects.create(
            organization=self.org,
            employee=self.employee,
            component=self.component,
            arrear_type=Arrear.ArrearType.DEDUCTION,
            from_month=1,
            from_year=2026,
            to_month=1,
            to_year=2026,
            amount=Decimal('50.00'),
            reason='Deduction'
        )
        
        # Access my_arrears
        response = self.emp_client.get(reverse('my_arrears'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['pending_earnings'], Decimal('150.00'))
        self.assertEqual(response.context['pending_recoveries'], Decimal('50.00'))
