from decimal import Decimal
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from accounts.models import Organization
from datetime import date, timedelta
from django.utils import timezone
from employees.models import Employee
from attendance.models import Attendance, AttendanceStatus
from leaves.models import LeaveCategory, LeaveRequest, LeaveType
from payroll.models import (
    Arrear, SalaryComponent, FinancialYear, TaxRegime, TaxSlab,
    TaxDeclarationCategory, EmployeeTaxProfile, EmployeeTaxDeclaration,
    DeclarationProof, DeclarationWorkflowLog, TaxCalculationSnapshot,
    PayrollTDSSyncLog, PayrollRun, SalaryStructure, SalaryStructureItem,
    EmployeePayslip
)
from payroll.engine.processor import PayrollProcessor
from payroll.engine.tax_calculator import TaxCalculatorEngine

User = get_user_model()


class PayrollAttendanceIntegrationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Payroll Org")
        self.employee = Employee.objects.create(
            organization=self.org,
            employee_id="EMP-PAY-001",
            first_name="Aarav",
            last_name="Mehta",
            email="aarav@example.com",
            phone_number="9999999999",
            is_active=True,
        )
        self.present_status = AttendanceStatus.objects.create(
            organization=self.org,
            name="Present",
            code="P",
            is_paid=True,
            payable_day_value=Decimal("1.00"),
            is_attendance_counted=True,
        )
        self.basic_component = SalaryComponent.objects.create(
            organization=self.org,
            code="BASIC_TEST",
            name="Basic Test",
            component_type=SalaryComponent.ComponentType.EARNING,
            calculation_type=SalaryComponent.CalculationType.FIXED,
            is_calculated_on_attendance=True,
        )
        self.structure = SalaryStructure.objects.create(
            organization=self.org,
            employee=self.employee,
            ctc=Decimal("264000.00"),
            gross_salary=Decimal("22000.00"),
            basic_salary=Decimal("22000.00"),
            effective_date=date(2026, 1, 1),
        )
        SalaryStructureItem.objects.create(
            organization=self.org,
            salary_structure=self.structure,
            component=self.basic_component,
            fixed_amount=Decimal("22000.00"),
        )

    def test_payroll_uses_attendance_paid_leave_and_lop_leave(self):
        working_dates = self._weekdays(2026, 5)
        attendance_dates = working_dates[:18]
        paid_leave_dates = working_dates[18:20]
        lop_leave_date = working_dates[20]

        for attendance_date in attendance_dates:
            Attendance.objects.create(
                organization=self.org,
                employee=self.employee,
                date=attendance_date,
                status=self.present_status,
            )

        paid_category = LeaveCategory.objects.create(
            organization=self.org,
            name="Paid Leave",
            code="PAID_TEST",
            is_paid_category=True,
        )
        paid_leave_type = LeaveType.objects.create(
            organization=self.org,
            category=paid_category,
            name="Earned Leave Test",
            code="ELT",
            is_paid=True,
            status="ACTIVE",
        )
        lop_category = LeaveCategory.objects.create(
            organization=self.org,
            name="Unpaid Leave",
            code="LOP_TEST",
            is_paid_category=False,
        )
        lop_leave_type = LeaveType.objects.create(
            organization=self.org,
            category=lop_category,
            name="Loss of Pay Test",
            code="LOPT",
            is_paid=False,
            status="ACTIVE",
        )

        LeaveRequest.objects.create(
            organization=self.org,
            employee=self.employee,
            leave_type=paid_leave_type,
            start_date=paid_leave_dates[0],
            end_date=paid_leave_dates[-1],
            total_days=Decimal("2.0"),
            payable_days=Decimal("2.00"),
            lop_days=Decimal("0.00"),
            reason="Approved paid leave",
            status="APPROVED",
            applied_at=timezone.now(),
        )
        LeaveRequest.objects.create(
            organization=self.org,
            employee=self.employee,
            leave_type=lop_leave_type,
            start_date=lop_leave_date,
            end_date=lop_leave_date,
            total_days=Decimal("1.0"),
            payable_days=Decimal("0.00"),
            lop_days=Decimal("1.00"),
            reason="Approved LOP",
            status="APPROVED",
            applied_at=timezone.now(),
        )

        payroll_run = PayrollRun.objects.create(
            organization=self.org,
            month=5,
            year=2026,
        )

        processed_count = PayrollProcessor(payroll_run.id).process()

        self.assertEqual(processed_count, 1)
        payslip = EmployeePayslip.objects.get(payroll_run=payroll_run, employee=self.employee)
        expected_working_days = Decimal(str(len(working_dates))).quantize(Decimal("0.01"))
        expected_paid_days = Decimal("20.00")
        expected_amount = (Decimal("22000.00") * expected_paid_days / expected_working_days).quantize(Decimal("0.01"))

        self.assertEqual(payslip.total_working_days, len(working_dates))
        self.assertEqual(payslip.paid_days, expected_paid_days)
        self.assertEqual(payslip.lop_days, Decimal("1.00"))
        self.assertIn("Paid leave: 2.00", payslip.remarks)
        self.assertIn("LOP leave: 1.00", payslip.remarks)
        self.assertEqual(payslip.items.get(component=self.basic_component).amount, expected_amount)

    @staticmethod
    def _weekdays(year, month):
        current = date(year, month, 1)
        dates = []
        while current.month == month:
            if current.weekday() < 5:
                dates.append(current)
            current += timedelta(days=1)
        return dates

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


class TaxDeclarationTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Org")
        self.admin_user = User.objects.create_user(
            username="admin", email="admin@test.com", password="password123",
            is_staff=True, organization=self.org
        )
        self.emp_user = User.objects.create_user(
            username="employee", email="emp@test.com", password="password123",
            is_staff=False, organization=self.org
        )
        self.employee = Employee.objects.create(
            organization=self.org,
            employee_id="EMP002",
            first_name="Jane",
            last_name="Doe",
            email="emp@test.com",
            phone_number="0987654321",
            is_active=True
        )
        self.admin_client = Client()
        self.admin_client.login(username="admin", password="password123")
        
        self.emp_client = Client()
        self.emp_client.login(username="employee", password="password123")

        # Set up financial year
        self.fy = FinancialYear.objects.create(
            name="2024-2025",
            start_date=date(2024, 4, 1),
            end_date=date(2025, 3, 31),
            is_active=True
        )

        # Set up Old Tax Regime
        self.old_regime = TaxRegime.objects.create(
            financial_year=self.fy,
            regime_type=TaxRegime.RegimeType.OLD,
            standard_deduction=Decimal("50000.00"),
            rebate_limit=Decimal("500000.00"),
            rebate_max_amount=Decimal("12500.00")
        )
        # Slabs for Old Regime
        TaxSlab.objects.create(regime=self.old_regime, min_income=Decimal("0.00"), max_income=Decimal("250000.00"), tax_rate=Decimal("0.00"))
        TaxSlab.objects.create(regime=self.old_regime, min_income=Decimal("250000.00"), max_income=Decimal("500000.00"), tax_rate=Decimal("5.00"))
        TaxSlab.objects.create(regime=self.old_regime, min_income=Decimal("500000.00"), max_income=Decimal("1000000.00"), tax_rate=Decimal("20.00"))
        TaxSlab.objects.create(regime=self.old_regime, min_income=Decimal("1000000.00"), max_income=None, tax_rate=Decimal("30.00"))

        # Set up New Tax Regime
        self.new_regime = TaxRegime.objects.create(
            financial_year=self.fy,
            regime_type=TaxRegime.RegimeType.NEW,
            standard_deduction=Decimal("50000.00"),
            rebate_limit=Decimal("700000.00"),
            rebate_max_amount=Decimal("25000.00")
        )
        # Slabs for New Regime
        TaxSlab.objects.create(regime=self.new_regime, min_income=Decimal("0.00"), max_income=Decimal("300000.00"), tax_rate=Decimal("0.00"))
        TaxSlab.objects.create(regime=self.new_regime, min_income=Decimal("300000.00"), max_income=Decimal("600000.00"), tax_rate=Decimal("5.00"))
        TaxSlab.objects.create(regime=self.new_regime, min_income=Decimal("600000.00"), max_income=Decimal("900000.00"), tax_rate=Decimal("10.00"))
        TaxSlab.objects.create(regime=self.new_regime, min_income=Decimal("900000.00"), max_income=Decimal("1200000.00"), tax_rate=Decimal("15.00"))
        TaxSlab.objects.create(regime=self.new_regime, min_income=Decimal("1200000.00"), max_income=Decimal("1500000.00"), tax_rate=Decimal("20.00"))
        TaxSlab.objects.create(regime=self.new_regime, min_income=Decimal("1500000.00"), max_income=None, tax_rate=Decimal("30.00"))

        # Set up active categories
        self.cat_80c = TaxDeclarationCategory.objects.create(
            code="SEC_80C",
            name="Section 80C",
            max_limit=Decimal("150000.00"),
            is_proof_required=True,
            applicable_regime=TaxDeclarationCategory.ApplicableRegime.OLD,
            display_order=10
        )
        self.cat_other = TaxDeclarationCategory.objects.create(
            code="OTHER_INCOME",
            name="Income from Other Sources",
            max_limit=None,
            is_proof_required=False,
            applicable_regime=TaxDeclarationCategory.ApplicableRegime.BOTH,
            display_order=90
        )

        # Create Profile
        self.profile = EmployeeTaxProfile.objects.create(
            employee=self.employee,
            financial_year=self.fy,
            selected_regime=self.new_regime,
            annual_ctc=Decimal("1200000.00"),
            basic_salary=Decimal("600000.00"),
            hra=Decimal("240000.00"),
            special_allowance=Decimal("360000.00")
        )

        # Pre-create Declarations
        self.decl_80c = EmployeeTaxDeclaration.objects.create(
            tax_profile=self.profile,
            category=self.cat_80c,
            declared_amount=Decimal("0.00"),
            approved_amount=Decimal("0.00"),
            workflow_status=EmployeeTaxDeclaration.WorkflowStatus.DRAFT
        )
        self.decl_other = EmployeeTaxDeclaration.objects.create(
            tax_profile=self.profile,
            category=self.cat_other,
            declared_amount=Decimal("0.00"),
            approved_amount=Decimal("0.00"),
            workflow_status=EmployeeTaxDeclaration.WorkflowStatus.DRAFT
        )

    def test_tax_calculator_new_regime_no_declarations(self):
        calc = TaxCalculatorEngine.calculate_tax(self.profile, self.new_regime)
        self.assertEqual(calc["gross_income"], 1200000.00)
        self.assertEqual(calc["taxable_income"], 1150000.00)
        self.assertEqual(calc["total_tax_liability"], 85800.00)
        self.assertEqual(calc["monthly_tds"], 7150.00)

    def test_tax_calculator_old_regime_with_80c(self):
        self.profile.selected_regime = self.old_regime
        self.profile.save()

        self.decl_80c.declared_amount = Decimal("150000.00")
        self.decl_80c.save()

        calc = TaxCalculatorEngine.calculate_tax(self.profile, self.old_regime, use_approved=False)
        self.assertEqual(calc["taxable_income"], 1000000.00)
        self.assertEqual(calc["total_tax_liability"], 117000.00)
        self.assertEqual(calc["monthly_tds"], 9750.00)

    def test_regime_locking_employee_portal(self):
        self.profile.is_regime_locked = True
        self.profile.save()

        url = reverse('my_tax_declarations')
        data = {
            'action_type': 'save_draft',
            'regime_type': 'OLD',
            'rent_paid': '120000'
        }
        response = self.emp_client.post(url, data)
        self.assertRedirects(response, url)

        self.profile.refresh_from_db()
        self.assertEqual(self.profile.selected_regime, self.new_regime)
        self.assertEqual(self.profile.rent_paid, Decimal("0.00"))

    def test_employee_dashboard_renders(self):
        url = reverse('my_tax_declarations')
        response = self.emp_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "2024-2025")

    def test_admin_lock_profile_toggle(self):
        url = reverse('admin_lock_profile', args=[self.profile.id])
        response = self.admin_client.get(url)
        self.assertRedirects(response, reverse('admin_tax_review'))
        
        self.profile.refresh_from_db()
        self.assertTrue(self.profile.is_regime_locked)

        # Toggle back
        response = self.admin_client.get(url)
        self.profile.refresh_from_db()
        self.assertFalse(self.profile.is_regime_locked)
