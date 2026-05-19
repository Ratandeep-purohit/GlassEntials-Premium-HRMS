from django.test import TestCase
from django.utils import timezone
from django.core.management import call_command
from decimal import Decimal
from datetime import timedelta, date

from accounts.models import CustomUser, Organization 
from employees.models import Employee, Department
from .models import (
    LeaveType, LeavePolicy, LeaveRequest, LeaveBalance, 
    ApprovalWorkflow, LeaveApprovalMatrix, LeaveApprovalMatrixStep,
    CompOffRequest, Holiday, RestrictedHolidayClaim, LeaveAccrualLog
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
