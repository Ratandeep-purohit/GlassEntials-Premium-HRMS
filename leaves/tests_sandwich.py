"""
Automated tests for the Sandwich Leave Policy.

Run with:
    python manage.py test leaves.tests_sandwich
"""
from datetime import date
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase


# ── helpers ─────────────────────────────────────────────────────────────────

def _make_leave_type(code='CL', count_weekends=False, count_holidays=False):
    """Return a mock LeaveType with an optional LeaveSandwichRule attached."""
    lt = MagicMock()
    lt.code = code

    rule = MagicMock()
    rule.enabled = True
    rule.count_weekends_between_leave = count_weekends
    rule.count_holidays_between_leave = count_holidays
    lt.sandwich_rule_config = rule
    return lt


def _calc(org, leave_type, start, end, session='FULL', holidays=None):
    """Thin wrapper so we don't repeat boilerplate in every test."""
    from leaves.services.calendar_engine import LeaveCalendarEngine
    with patch(
        'leaves.services.calendar_engine.HolidayCalendarService.holiday_dates_for_period',
        return_value=holidays or set(),
    ):
        return LeaveCalendarEngine.calculate_days(
            organization=org,
            leave_type=leave_type,
            start_date=start,
            end_date=end,
            session_type=session,
        )


def _make_org(sandwich_on):
    """Return a fake org whose AttendanceSettings.sandwich_leave_policy == sandwich_on."""
    org = MagicMock()
    return org, sandwich_on  # passed together to _calc_with_policy


def _calc_policy(sandwich_on, start, end, session='FULL', holidays=None,
                 count_weekends_lt=False, count_holidays_lt=False):
    """
    Call calculate_days with sandwich_leave_policy = sandwich_on.
    Uses Sunday (weekday 6) as the only weekly off.
    """
    from leaves.services.calendar_engine import LeaveCalendarEngine
    org = MagicMock()
    leave_type = _make_leave_type(
        count_weekends=count_weekends_lt,
        count_holidays=count_holidays_lt,
    )
    with patch(
        'leaves.services.calendar_engine.HolidayCalendarService.holiday_dates_for_period',
        return_value=holidays or set(),
    ), patch(
        'leaves.services.calendar_engine._get_org_sandwich_policy',
        return_value=sandwich_on,
    ):
        return LeaveCalendarEngine.calculate_days(
            organization=org,
            leave_type=leave_type,
            start_date=start,
            end_date=end,
            session_type=session,
        )


# Week containing our test dates:
# Mon 2026-09-07, Tue 08, Wed 09, Thu 10, Fri 11, Sat 12, Sun 13

class SandwichPolicyOffTests(TestCase):
    """Policy OFF — classic behaviour: Sundays are never counted."""

    def test_policy_off_leave_around_sunday(self):
        # Sat 12 = Leave, Sun 13 = weekly off, Mon 14 = Leave
        result = _calc_policy(False, date(2026, 9, 12), date(2026, 9, 14))
        self.assertEqual(result, Decimal('2.00'))

    def test_policy_off_no_sandwich(self):
        # Mon 07 = Leave only
        result = _calc_policy(False, date(2026, 9, 7), date(2026, 9, 7))
        self.assertEqual(result, Decimal('1.00'))

    def test_leave_only_before_weekly_off(self):
        # Fri 11 = Leave, Sat 12 = weekly off (for this test treat Sat as off too)
        # Only Sunday is weekly off in our system, so Sat counts as work-day.
        # Fri 11 = Leave, Sun 13 = weekly off -> range Fri-Sun has 2 work days (Fri+Sat)
        result = _calc_policy(False, date(2026, 9, 11), date(2026, 9, 13))
        self.assertEqual(result, Decimal('2.00'))  # Fri + Sat; Sun excluded

    def test_leave_only_after_weekly_off(self):
        # Sun 13 weekly off → Mon 14 = Leave. Range Sun-Mon: 1 work day
        result = _calc_policy(False, date(2026, 9, 13), date(2026, 9, 14))
        self.assertEqual(result, Decimal('1.00'))


class SandwichPolicyOnTests(TestCase):
    """Policy ON — weekly offs between leave days must be counted."""

    def test_sat_sun_mon_equals_3(self):
        # Sat 12 = Leave, Sun 13 = weekly off, Mon 14 = Leave → 3 days
        result = _calc_policy(True, date(2026, 9, 12), date(2026, 9, 14))
        self.assertEqual(result, Decimal('3.00'))

    def test_multiple_weekoffs_between_leave(self):
        # Fri 11, Sat 12 = Leave (work), Sun 13 = weekly off, Mon 14 = Leave
        # Sun is sandwiched → 4 days
        result = _calc_policy(True, date(2026, 9, 11), date(2026, 9, 14))
        self.assertEqual(result, Decimal('4.00'))

    def test_two_consecutive_sundays_sandwiched(self):
        # Multi-week range: Sat 12 = Leave, Sun 13 = weekly off, Mon 14–Fri 18,
        # Sat 19, Sun 20 = weekly off, Mon 21 = Leave → 2 Sundays sandwiched
        # Range: Sat 12 → Mon 21 → includes Sun 13 + Sun 20 as off
        result = _calc_policy(True, date(2026, 9, 12), date(2026, 9, 21))
        # Sat12(1) + Sun13(sandwich=1) + Mon14–Fri18(5) + Sat19(1) + Sun20(sandwich=1) + Mon21(1) = 10
        self.assertEqual(result, Decimal('10.00'))

    def test_leave_only_before_weekly_off(self):
        # Case 3: Fri Leave, Sun weekly off, Mon present → range Fri-Sun
        # No work day after the Sunday in range → Sunday NOT sandwiched
        result = _calc_policy(True, date(2026, 9, 11), date(2026, 9, 13))
        self.assertEqual(result, Decimal('2.00'))  # Fri + Sat only

    def test_leave_only_after_weekly_off(self):
        # Case 4: Sun weekly off, Mon Leave → range Sun-Mon
        result = _calc_policy(True, date(2026, 9, 13), date(2026, 9, 14))
        self.assertEqual(result, Decimal('1.00'))

    def test_holiday_between_leave_days(self):
        # Mon 07 = Leave, Tue 08 = Holiday, Wed 09 = Leave  (holiday sandwiched)
        result = _calc_policy(
            True,
            date(2026, 9, 7),
            date(2026, 9, 9),
            holidays={date(2026, 9, 8)},
        )
        self.assertEqual(result, Decimal('3.00'))

    def test_holiday_between_leave_policy_off(self):
        # Same scenario but policy OFF → holiday not counted
        result = _calc_policy(
            False,
            date(2026, 9, 7),
            date(2026, 9, 9),
            holidays={date(2026, 9, 8)},
        )
        self.assertEqual(result, Decimal('2.00'))

    def test_half_day_ignores_sandwich(self):
        # Half-day sessions always return 0.5 regardless of sandwich policy
        result = _calc_policy(True, date(2026, 9, 12), date(2026, 9, 14), session='MORNING')
        self.assertEqual(result, Decimal('0.50'))

    def test_long_leave_with_weekends(self):
        # Fri 11 → Wed 16: includes Sun 13 as weekly off
        # Fri 11(1) + Sat 12(1) + Sun 13(sandwich=1) + Mon 14(1) + Tue 15(1) + Wed 16(1) = 6
        result = _calc_policy(True, date(2026, 9, 11), date(2026, 9, 16))
        self.assertEqual(result, Decimal('6.00'))

    def test_org_isolation(self):
        """Different org settings must not leak across organizations."""
        # Org A: sandwich ON  → 3 days
        result_on = _calc_policy(True, date(2026, 9, 12), date(2026, 9, 14))
        # Org B: sandwich OFF → 2 days
        result_off = _calc_policy(False, date(2026, 9, 12), date(2026, 9, 14))
        self.assertEqual(result_on, Decimal('3.00'))
        self.assertEqual(result_off, Decimal('2.00'))


class SandwichDayCountTests(TestCase):
    """Test the sandwich_day_count helper."""

    def test_count_returns_zero_when_policy_off(self):
        from leaves.services.calendar_engine import LeaveCalendarEngine
        org = MagicMock()
        lt = _make_leave_type()
        with patch('leaves.services.calendar_engine._get_org_sandwich_policy', return_value=False), \
             patch('leaves.services.calendar_engine.HolidayCalendarService.holiday_dates_for_period',
                   return_value=set()):
            total, sw = LeaveCalendarEngine.sandwich_day_count(
                organization=org,
                leave_type=lt,
                start_date=date(2026, 9, 12),
                end_date=date(2026, 9, 14),
            )
        self.assertEqual(sw, 0)
        self.assertEqual(total, Decimal('2.00'))

    def test_count_returns_one_when_policy_on(self):
        from leaves.services.calendar_engine import LeaveCalendarEngine
        org = MagicMock()
        lt = _make_leave_type()
        with patch('leaves.services.calendar_engine._get_org_sandwich_policy', return_value=True), \
             patch('leaves.services.calendar_engine.HolidayCalendarService.holiday_dates_for_period',
                   return_value=set()):
            total, sw = LeaveCalendarEngine.sandwich_day_count(
                organization=org,
                leave_type=lt,
                start_date=date(2026, 9, 12),
                end_date=date(2026, 9, 14),
            )
        self.assertEqual(sw, 1)
        self.assertEqual(total, Decimal('3.00'))
