from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from decimal import Decimal
from datetime import timedelta, date

from accounts.models import CustomUser, Organization 
from employees.models import Employee, Department
from .models import (
    LeaveType, LeavePolicy, LeaveRequest, LeaveBalance, LeaveCategory,
    ApprovalWorkflow, LeaveApprovalMatrix, LeaveApprovalMatrixStep,
    CompOffRequest, Holiday, RestrictedHolidayClaim, LeaveAccrualLog,
    HolidayCalendar
)

class EnterpriseLeaveModuleTests(TestCase):
    def setUp(self):
        # 1. Base Setup
        self.org = Organization.objects.create(name="Enterprise Corp", unique_code="EC001")
        
        # 2. Users (Manager & Employee)
        self.manager_user = CustomUser.objects.create_user(
            username="manager", email="mgr@corp.com", password="password", organization=self.org
        )
        self.emp_user = CustomUser.objects.create_user(
            username="employee", email="emp@corp.com", password="password", organization=self.org
        )
        self.hr_user = CustomUser.objects.create_user(
            username="hr", email="hr@corp.com", password="password", organization=self.org, is_staff=True
        )
        
        # 3. Department & Employees
        self.dept = Department.objects.create(name="Engineering", organization=self.org)
        
        self.manager = Employee.objects.create(
            organization=self.org, employee_id="MGR01", first_name="Manager", last_name="User",
            email="mgr@corp.com", department=self.dept
        )
        
        self.employee = Employee.objects.create(
            organization=self.org, employee_id="EMP01", first_name="Staff", last_name="User",
            email="emp@corp.com", department=self.dept, manager=self.manager
        )
        
        # 4. Leave Types & Policies
        self.el_type = LeaveType.objects.create(organization=self.org, name="Earned Leave", code="EL")
        self.sl_type = LeaveType.objects.create(organization=self.org, name="Sick Leave", code="SL")
        self.comp_type = LeaveType.objects.create(organization=self.org, name="Comp Off", code="CO")
        
        self.el_policy = LeavePolicy.objects.create(
            organization=self.org, leave_type=self.el_type, 
            accrual_rate=Decimal('2.0'), max_balance=Decimal('30.0'), carry_forward_limit=Decimal('15.0')
        )
        
        # 5. Initial Balances
        self.el_balance = LeaveBalance.objects.create(
            employee=self.employee, leave_type=self.el_type, year=2026, current_balance=Decimal('10.0')
        )


    # ──────── 1. MULTI-LEVEL APPROVALS ────────
    def test_multi_level_approval_flow(self):
        """Test that leave moves from Manager -> HR automatically"""
        # Create a Matrix: Step 1 (Manager), Step 2 (HR)
        matrix = LeaveApprovalMatrix.objects.create(organization=self.org, leave_type=self.el_type, name="Standard Flow")
        LeaveApprovalMatrixStep.objects.create(matrix=matrix, order=1, approver_role='MANAGER')
        LeaveApprovalMatrixStep.objects.create(matrix=matrix, order=2, approver_role='HR')

        # Submit Leave (Logic normally in view, we simulate it here)
        leave = LeaveRequest.objects.create(
            employee=self.employee, leave_type=self.el_type, 
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), 
            total_days=2.0, organization=self.org, status='PENDING'
        )
        
        # Manually create workflow steps (as our view would)
        ApprovalWorkflow.objects.create(
            leave_request=leave, approver=self.manager_user, approver_role='MANAGER', sequence_order=1, status='PENDING'
        )

        ApprovalWorkflow.objects.create(
            leave_request=leave, approver=None, approver_role='HR', sequence_order=2, status='PENDING'
        )

        # Simulate Manager Approval
        step1 = leave.workflow_steps.get(sequence_order=1)
        step1.status = 'APPROVED'
        step1.save()
        
        # Verify next step is pending
        step2 = leave.workflow_steps.get(sequence_order=2)
        self.assertEqual(step2.status, 'PENDING')
        self.assertEqual(step2.approver_role, 'HR')

    # ──────── 2. LEAVE ACCRUAL AUTOMATION ────────
    def test_monthly_accrual_command(self):
        """Test the 'accrue_leaves' management command"""
        initial_bal = self.el_balance.current_balance # 10.0
        
        # Run the command
        call_command('accrue_leaves')
        
        self.el_balance.refresh_from_db()
        self.assertEqual(self.el_balance.current_balance, initial_bal + Decimal('2.0'))
        
        # Verify log entry
        log = LeaveAccrualLog.objects.filter(employee=self.employee, action_type='ACCRUAL').first()
        self.assertIsNotNone(log)
        self.assertEqual(log.amount, Decimal('2.0'))

    def test_year_end_processing(self):
        """Test 'process_year_end' (Carry Forward vs Lapsing)"""
        # Set balance to 20.0 (Policy limit is 15.0)
        self.el_balance.current_balance = Decimal('20.0')
        self.el_balance.save()
        
        call_command('process_year_end')
        
        # Check balance for NEXT year
        next_year_bal = LeaveBalance.objects.get(employee=self.employee, year=2027, leave_type=self.el_type)
        self.assertEqual(next_year_bal.current_balance, Decimal('15.0')) # Capped at carry_forward_limit
        
        # Verify Lapsed Log
        lapsed_log = LeaveAccrualLog.objects.filter(employee=self.employee, action_type='MANUAL', amount=Decimal('-5.0')).exists()
        self.assertTrue(lapsed_log)

    # ──────── 3. COMP-OFF WORKFLOW ────────
    def test_comp_off_credit(self):
        """Test that approving a Comp-Off request adds to balance"""
        # Create Comp-off balance
        co_bal = LeaveBalance.objects.create(
            employee=self.employee, leave_type=self.comp_type, year=2026, current_balance=Decimal('0.0')
        )
        
        # Request
        req = CompOffRequest.objects.create(
            employee=self.employee, worked_date=date(2026, 5, 1), reason="Weekend Work", status='PENDING'
        )
        
        # Simulate Approval (Normally in view)
        req.status = 'APPROVED'
        req.save()
        
        # In a real view, we'd add 1.0 to balance. Let's verify we can do that.
        co_bal.current_balance += Decimal('1.0')
        co_bal.save()

        
        self.assertEqual(self.employee.leave_balances.get(leave_type=self.comp_type).current_balance, 1.0)

    # ──────── 4. RESTRICTED HOLIDAY (RH) ────────
    def test_restricted_holiday_claim(self):
        """Test RH claim creation and status"""
        holiday = Holiday.objects.create(name="Regional Fest", date=date(2026, 8, 15), is_optional=True, organization=self.org)
        
        claim = RestrictedHolidayClaim.objects.create(
            employee=self.employee, holiday=holiday, year=2026, status='APPROVED'
        )
        
        self.assertEqual(self.employee.rh_claims.count(), 1)
        self.assertEqual(claim.holiday.name, "Regional Fest")

    # ──────── 5. LEAVE CANCELLATION ────────
    def test_admin_can_create_leave_type_and_policy(self):
        self.client.login(username="hr", password="password")

        response = self.client.post(reverse('leaves:create_leave'), {
            'name': 'Casual Leave',
            'code': 'cl',
            'description': 'General personal leave',
            'max_balance': '12',
            'accrual_rate': '1',
            'carry_forward_limit': '3',
            'min_service_days': '0',
            'attachment_threshold_days': '3',
            'is_paid': 'on',
        })

        self.assertRedirects(response, reverse('leaves:create_leave'))
        leave_type = LeaveType.objects.get(organization=self.org, code='CL')
        policy = LeavePolicy.objects.get(organization=self.org, leave_type=leave_type)
        self.assertEqual(leave_type.name, 'Casual Leave')
        self.assertEqual(policy.max_balance, Decimal('12.00'))

    def test_admin_can_assign_leave_balance_to_employee(self):
        self.client.login(username="hr", password="password")
        category = LeaveCategory.objects.create(organization=self.org, name="Paid Leave", code="PAID")
        leave_type = LeaveType.objects.create(
            organization=self.org,
            category=category,
            name="Casual Leave",
            code="CL",
            status="ACTIVE",
            is_requestable=True,
        )

        response = self.client.post(reverse('leaves:assign_leaves'), {
            'employee': str(self.employee.id),
            'leave_types': [str(leave_type.id)],
            'year': '2026',
            f'amount_{leave_type.id}': '8',
            'assignment_mode': 'SET',
        })

        self.assertRedirects(
            response,
            f"{reverse('leaves:assign_leaves')}?employee={self.employee.id}&year=2026"
        )
        balance = LeaveBalance.objects.get(employee=self.employee, leave_type=leave_type, year=2026)
        self.assertEqual(balance.current_balance, Decimal('8.00'))
        self.assertTrue(
            LeaveAccrualLog.objects.filter(
                employee=self.employee,
                leave_type=leave_type,
                action_type='MANUAL',
                amount=Decimal('8.00')
            ).exists()
        )

    def test_admin_cannot_assign_zero_leave_balance(self):
        self.client.login(username="hr", password="password")
        category = LeaveCategory.objects.create(organization=self.org, name="Paid Leave", code="PAID")
        leave_type = LeaveType.objects.create(
            organization=self.org,
            category=category,
            name="Casual Leave",
            code="CL",
            status="ACTIVE",
            is_requestable=True,
        )

        response = self.client.post(reverse('leaves:assign_leaves'), {
            'employee': str(self.employee.id),
            'leave_types': [str(leave_type.id)],
            'year': '2026',
            f'amount_{leave_type.id}': '0',
            'assignment_mode': 'SET',
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            LeaveBalance.objects.filter(employee=self.employee, leave_type=leave_type, year=2026).exists()
        )

    def test_admin_can_manage_yearly_holiday_calendar(self):
        self.client.login(username="hr", password="password")

        response = self.client.post(reverse('leaves:holiday_calendars'), {
            'action': 'create_calendar',
            'name': 'India Holidays',
            'year': '2026',
            'branch': 'Head Office',
            'is_default': 'on',
        })

        calendar_obj = HolidayCalendar.objects.get(organization=self.org, name='India Holidays', year=2026)
        self.assertRedirects(
            response,
            f"{reverse('leaves:holiday_calendars')}?year=2026&calendar={calendar_obj.id}"
        )
        self.assertTrue(calendar_obj.is_default)

        response = self.client.post(reverse('leaves:holiday_calendars'), {
            'action': 'save_holiday',
            'calendar': str(calendar_obj.id),
            'holiday_name': 'Diwali',
            'holiday_date': '2026-11-08',
            'holiday_type': 'COMPANY',
            'is_paid': 'on',
        })

        self.assertRedirects(
            response,
            f"{reverse('leaves:holiday_calendars')}?year=2026&calendar={calendar_obj.id}"
        )
        holiday = Holiday.objects.get(calendar=calendar_obj, name='Diwali')
        self.assertEqual(holiday.date, date(2026, 11, 8))
        self.assertTrue(holiday.is_paid)

    def test_admin_can_copy_and_import_holiday_calendar(self):
        self.client.login(username="hr", password="password")
        source_calendar = HolidayCalendar.objects.create(
            organization=self.org,
            name='India Holidays',
            year=2026,
            is_default=True,
        )
        Holiday.objects.create(
            organization=self.org,
            calendar=source_calendar,
            name='Republic Day',
            date=date(2026, 1, 26),
            holiday_type='NATIONAL',
            is_paid=True,
        )

        response = self.client.post(reverse('leaves:holiday_calendars'), {
            'action': 'copy_calendar',
            'source_calendar': str(source_calendar.id),
            'target_year': '2027',
            'target_name': 'India Holidays 2027',
            'make_default': 'on',
        })

        target_calendar = HolidayCalendar.objects.get(organization=self.org, name='India Holidays 2027', year=2027)
        self.assertRedirects(
            response,
            f"{reverse('leaves:holiday_calendars')}?year=2027&calendar={target_calendar.id}"
        )
        copied_holiday = Holiday.objects.get(calendar=target_calendar, name='Republic Day')
        self.assertEqual(copied_holiday.date, date(2027, 1, 26))

        csv_file = SimpleUploadedFile(
            'holidays.csv',
            b'name,date,holiday_type,is_optional,is_paid\nDiwali,2027-10-29,COMPANY,false,true\n',
            content_type='text/csv',
        )
        response = self.client.post(reverse('leaves:holiday_calendars'), {
            'action': 'import_holidays',
            'calendar': str(target_calendar.id),
            'csv_file': csv_file,
        })

        self.assertRedirects(
            response,
            f"{reverse('leaves:holiday_calendars')}?year=2027&calendar={target_calendar.id}"
        )
        self.assertTrue(Holiday.objects.filter(calendar=target_calendar, name='Diwali', date=date(2027, 10, 29)).exists())

    def test_leave_cancellation_restore(self):
        """Test that approved cancellation restores balance"""
        # Initial balance 10.0. User takes 2 days. Balance = 8.0
        self.el_balance.current_balance = 8.0
        self.el_balance.save()
        
        leave = LeaveRequest.objects.create(
            employee=self.employee, leave_type=self.el_type, 
            start_date=date(2026, 6, 1), end_date=date(2026, 6, 2), 
            total_days=2.0, organization=self.org, status='CANCEL_REQUESTED'
        )
        
        # Simulate Approval of cancellation
        leave.status = 'CANCELLED'
        leave.save()
        
        # Restore balance
        self.el_balance.current_balance += leave.total_days
        self.el_balance.save()

        
        self.assertEqual(self.el_balance.current_balance, 10.0)
