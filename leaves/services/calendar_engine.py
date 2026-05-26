from decimal import Decimal
from datetime import timedelta

from leaves.services.holiday_calendar_service import HolidayCalendarService


class LeaveCalendarEngine:
    @staticmethod
    def calculate_days(*, organization, leave_type, start_date, end_date, session_type, employee=None):
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
        sandwich_rule = getattr(leave_type, "sandwich_rule_config", None)
        count_weekends = bool(sandwich_rule and sandwich_rule.enabled and sandwich_rule.count_weekends_between_leave)
        count_holidays = bool(sandwich_rule and sandwich_rule.enabled and sandwich_rule.count_holidays_between_leave)

        total = Decimal("0.00")
        current = start_date
        while current <= end_date:
            is_weekend = current.weekday() >= 5
            is_holiday = current in holidays
            if is_weekend and not count_weekends:
                current += timedelta(days=1)
                continue
            if is_holiday and not count_holidays:
                current += timedelta(days=1)
                continue
            total += Decimal("1.00")
            current += timedelta(days=1)
        return total
