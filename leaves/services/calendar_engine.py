from decimal import Decimal
from datetime import timedelta

from leaves.services.holiday_calendar_service import HolidayCalendarService


def _get_org_sandwich_policy(organization):
    """Return True if the org-level Sandwich Leave Policy is enabled."""
    try:
        from attendance.models import AttendanceSettings
        settings = AttendanceSettings.objects.filter(organization=organization).first()
        return bool(settings and settings.sandwich_leave_policy)
    except Exception:
        return False


def _get_weekly_off_days(organization):
    """
    Return a set of weekday integers (0=Monday … 6=Sunday) that are weekly offs.
    Currently the HRMS hardcodes Sunday (6) as the only weekly off because there
    is no WeeklyOff configuration model.  This function is the single place to
    update if a WeeklyOff model is added later.
    """
    return {6}   # Sunday


def _collect_sandwich_days(start_date, end_date, holidays, weekly_off_days):
    """
    Given a date range [start_date, end_date] (all of which are in the leave
    request), return the set of dates inside that range that are NON-WORKING
    days (weekly off or non-optional holiday) and are *sandwiched* — i.e., they
    have at least one actual leave day on both sides.

    Algorithm:
      1. Walk every date in [start_date, end_date].
      2. Classify each as 'work' or 'off'.
      3. Group consecutive 'off' runs.
      4. For each run, check whether there is a 'work' day strictly before AND
         strictly after the run (within the range).  If yes → those 'off' days
         count as sandwich leave.
    """
    dates = []
    current = start_date
    while current <= end_date:
        is_off = (current.weekday() in weekly_off_days) or (current in holidays)
        dates.append((current, is_off))
        current += timedelta(days=1)

    sandwich = set()
    n = len(dates)
    i = 0
    while i < n:
        date, is_off = dates[i]
        if not is_off:
            i += 1
            continue
        # Found start of an 'off' run
        run_start = i
        while i < n and dates[i][1]:
            i += 1
        run_end = i - 1  # inclusive

        # Check: is there a work day before this run?
        has_work_before = any(not dates[j][1] for j in range(0, run_start))
        # Check: is there a work day after this run?
        has_work_after = any(not dates[j][1] for j in range(run_end + 1, n))

        if has_work_before and has_work_after:
            for k in range(run_start, run_end + 1):
                sandwich.add(dates[k][0])

    return sandwich


class LeaveCalendarEngine:
    @staticmethod
    def calculate_days(*, organization, leave_type, start_date, end_date,
                       session_type, employee=None):
        """
        Calculate the number of leave days to deduct for a leave request.

        Priority:
          1. Half-day / short-leave sessions are returned immediately.
          2. Per-leave-type LeaveSandwichRule (existing) is respected.
          3. Org-level sandwich_leave_policy (new) acts as a global switch:
             when ON, weekly offs and non-optional holidays that fall strictly
             *between* leave days in the requested range are also counted.
        """
        if session_type in ["MORNING", "AFTERNOON"]:
            return Decimal("0.50")
        if session_type == "SHORT":
            return Decimal("1.00") if leave_type.code == "SHL" else Decimal("0.25")

        holidays = HolidayCalendarService.holiday_dates_for_period(
            organization=organization,
            start_date=start_date,
            end_date=end_date,
            employee=employee,
            include_optional=False,
        )

        # Per-leave-type sandwich rule (existing behaviour)
        sandwich_rule = getattr(leave_type, "sandwich_rule_config", None)
        count_weekends_lt = bool(
            sandwich_rule and sandwich_rule.enabled and sandwich_rule.count_weekends_between_leave
        )
        count_holidays_lt = bool(
            sandwich_rule and sandwich_rule.enabled and sandwich_rule.count_holidays_between_leave
        )

        # Org-level sandwich policy (new)
        org_sandwich = _get_org_sandwich_policy(organization)
        weekly_off_days = _get_weekly_off_days(organization)

        sandwich_days = set()
        if org_sandwich:
            sandwich_days = _collect_sandwich_days(
                start_date, end_date, holidays, weekly_off_days
            )

        total = Decimal("0.00")
        current = start_date
        while current <= end_date:
            is_weekend = current.weekday() in weekly_off_days
            is_holiday = current in holidays

            if is_weekend:
                # Count if: per-type rule says so OR org sandwich policy says so
                if count_weekends_lt or (current in sandwich_days):
                    total += Decimal("1.00")
                current += timedelta(days=1)
                continue

            if is_holiday:
                if count_holidays_lt or (current in sandwich_days):
                    total += Decimal("1.00")
                current += timedelta(days=1)
                continue

            total += Decimal("1.00")
            current += timedelta(days=1)

        return total

    @staticmethod
    def sandwich_day_count(*, organization, leave_type, start_date, end_date, employee=None):
        """
        Returns (total_days, sandwich_count) for the date range.
        Useful for the UI to show 'Includes N weekly off(s) due to Sandwich Policy'.
        """
        if not _get_org_sandwich_policy(organization):
            days = LeaveCalendarEngine.calculate_days(
                organization=organization,
                leave_type=leave_type,
                start_date=start_date,
                end_date=end_date,
                session_type='FULL',
                employee=employee,
            )
            return days, 0

        holidays = HolidayCalendarService.holiday_dates_for_period(
            organization=organization,
            start_date=start_date,
            end_date=end_date,
            employee=employee,
            include_optional=False,
        )
        weekly_off_days = _get_weekly_off_days(organization)
        sandwich_days = _collect_sandwich_days(start_date, end_date, holidays, weekly_off_days)

        total = LeaveCalendarEngine.calculate_days(
            organization=organization,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            session_type='FULL',
            employee=employee,
        )
        return total, len(sandwich_days)
