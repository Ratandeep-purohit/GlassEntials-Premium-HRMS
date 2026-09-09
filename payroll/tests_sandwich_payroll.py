"""
Payroll sandwich-policy tests for PayrollAttendanceService.

These tests verify that when sandwich_leave_policy=ON, weekly offs
sandwiched between absent working days are counted as extra LOP days.
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase

from payroll.engine.attendance_days import PayrollAttendanceService, PayrollDaySummary

ZERO = Decimal("0.00")


def _make_service(org, month=9, year=2026, holiday_dates=None, working_dates=None,
                  sandwich_policy=False, weekly_off_days=None):
    """Build a PayrollAttendanceService with all DB calls mocked out."""
    svc = object.__new__(PayrollAttendanceService)
    svc.organization = org
    svc.month = month
    svc.year = year
    svc.period_start = date(year, month, 1)
    svc.period_end = date(year, month, 30)
    svc.holiday_dates = holiday_dates or set()
    svc.sandwich_policy = sandwich_policy
    svc.weekly_off_days = weekly_off_days if weekly_off_days is not None else {6}  # Sunday

    if working_dates is not None:
        svc.working_dates = working_dates
    else:
        days = []
        cur = svc.period_start
        while cur <= svc.period_end:
            if cur.weekday() not in svc.weekly_off_days and cur not in svc.holiday_dates:
                days.append(cur)
            cur += timedelta(days=1)
        svc.working_dates = days

    svc.working_day_count = Decimal(str(len(svc.working_dates))).quantize(Decimal("0.01"))
    return svc


class SandwichPayrollPolicyOffTests(TestCase):
    def test_no_sandwich_when_policy_off(self):
        org = object()
        emp_id = 1
        svc = _make_service(org, sandwich_policy=False)
        per_day = {(emp_id, date(2026, 9, 1)): ZERO}
        extra = svc._sandwich_absent_extra_by_employee(per_day)
        self.assertEqual(extra, {})

    def test_summary_policy_off_no_extra_lop(self):
        org = object()
        svc = _make_service(org, sandwich_policy=False)
        summary = svc._build_summary(
            Decimal("24"), Decimal("0"), Decimal("0"),
            sandwich_lop_days=ZERO,
        )
        self.assertEqual(summary.sandwich_lop_days, ZERO)
        self.assertEqual(summary.absence_lop_days, Decimal("2"))
        self.assertEqual(summary.lop_days, Decimal("2"))


class SandwichPayrollPolicyOnTests(TestCase):
    def test_sat_absent_sun_off_mon_absent(self):
        """Sat absent + Sun weekly-off + Mon absent → 1 sandwich day."""
        org = object()
        emp_id = 1
        mon = date(2026, 9, 7)
        svc = _make_service(org, sandwich_policy=True)
        # dummy entry to register employee; all working days have payable=0
        per_day = {(emp_id, date(2026, 9, 1)): ZERO}
        extra = svc._sandwich_absent_extra_by_employee(per_day)
        self.assertIn(emp_id, extra)
        self.assertGreaterEqual(extra[emp_id], 1)

    def test_build_summary_adds_sandwich_lop(self):
        """sandwich_lop_days reduces paid_days and increases lop_days."""
        org = object()
        svc = _make_service(org, sandwich_policy=True)
        wdc = svc.working_day_count
        summary = svc._build_summary(
            Decimal("24"), Decimal("0"), Decimal("0"),
            sandwich_lop_days=Decimal("1"),
        )
        self.assertEqual(summary.sandwich_lop_days, Decimal("1"))
        self.assertEqual(summary.lop_days, Decimal("3"))
        self.assertEqual(summary.paid_days, wdc - Decimal("3"))

    def test_two_weekly_offs_sandwiched(self):
        """Fri absent + Sat WO + Sun WO + Mon absent → 2 sandwich days."""
        org = object()
        emp_id = 42
        svc = _make_service(org, sandwich_policy=True, weekly_off_days={5, 6})
        per_day = {(emp_id, date(2026, 9, 1)): ZERO}
        extra = svc._sandwich_absent_extra_by_employee(per_day)
        self.assertIn(emp_id, extra)
        self.assertGreaterEqual(extra[emp_id], 2)

    def test_absent_only_before_weekly_off(self):
        """Sat absent + Sun weekly-off + Mon PRESENT → 0 sandwich days."""
        org = object()
        emp_id = 7
        svc = _make_service(org, sandwich_policy=True)
        # Mark ALL working days present EXCEPT Sat Sep 5 (the day before target Sunday)
        sat = date(2026, 9, 5)
        per_day = {(emp_id, d): Decimal("1") for d in svc.working_dates if d != sat}
        extra = svc._sandwich_absent_extra_by_employee(per_day)
        # Sun Sep 6: prev=Sat(absent), next=Mon(present) → NOT sandwiched
        self.assertEqual(extra.get(emp_id, 0), 0)

    def test_absent_only_after_weekly_off(self):
        """Sat PRESENT + Sun weekly-off + Mon absent → 0 sandwich days."""
        org = object()
        emp_id = 8
        svc = _make_service(org, sandwich_policy=True)
        # Mark ALL working days present EXCEPT Mon Sep 7 (the day after target Sunday)
        mon = date(2026, 9, 7)
        per_day = {(emp_id, d): Decimal("1") for d in svc.working_dates if d != mon}
        extra = svc._sandwich_absent_extra_by_employee(per_day)
        # Sun Sep 6: prev=Sat(present), next=Mon(absent) → NOT sandwiched
        self.assertEqual(extra.get(emp_id, 0), 0)

    def test_org_isolation(self):
        """Org B (policy OFF) must not get sandwich days even with identical data."""
        org_a, org_b = object(), object()
        emp_id = 99
        svc_a = _make_service(org_a, sandwich_policy=True)
        svc_b = _make_service(org_b, sandwich_policy=False)
        per_day = {(emp_id, date(2026, 9, 1)): ZERO}
        self.assertEqual(svc_b._sandwich_absent_extra_by_employee(per_day), {})

    def test_remarks_include_sandwich_when_positive(self):
        org = object()
        svc = _make_service(org, sandwich_policy=True)
        summary = svc._build_summary(
            Decimal("24"), ZERO, ZERO,
            sandwich_lop_days=Decimal("1"),
        )
        self.assertIn("Sandwich LOP", summary.remarks)

    def test_remarks_silent_when_no_sandwich(self):
        org = object()
        svc = _make_service(org, sandwich_policy=False)
        summary = svc._build_summary(Decimal("24"), ZERO, ZERO)
        self.assertNotIn("Sandwich", summary.remarks)

    def test_present_employee_no_sandwich(self):
        """Employee present on ALL days must never get sandwich LOP."""
        org = object()
        emp_id = 5
        svc = _make_service(org, sandwich_policy=True)
        per_day = {(emp_id, d): Decimal("1") for d in svc.working_dates}
        extra = svc._sandwich_absent_extra_by_employee(per_day)
        self.assertEqual(extra.get(emp_id, 0), 0)
