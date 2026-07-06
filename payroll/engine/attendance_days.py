import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q

from attendance.models import Attendance
from leaves.models import LeavePayrollImpact, LeaveRequest
from leaves.services.holiday_calendar_service import HolidayCalendarService


ZERO = Decimal("0.00")
ONE = Decimal("1.00")


@dataclass(frozen=True)
class PayrollDaySummary:
    working_days: Decimal
    paid_days: Decimal
    lop_days: Decimal
    attendance_paid_days: Decimal
    paid_leave_days: Decimal
    lop_leave_days: Decimal
    absence_lop_days: Decimal
    holidays: int

    @property
    def remarks(self):
        return (
            f"Working days: {self.working_days}; "
            f"Attendance paid: {self.attendance_paid_days}; "
            f"Paid leave: {self.paid_leave_days}; "
            f"LOP leave: {self.lop_leave_days}; "
            f"Absent LOP: {self.absence_lop_days}"
        )


class PayrollAttendanceService:
    """
    Calculates payroll-ready paid/LOP days.

    Current enterprise baseline:
    - Monday-Friday are payable work days.
    - Paid, non-optional holidays reduce payable work days.
    - AttendanceStatus.payable_day_value supports present/half-day/paid statuses.
    - Approved leaves create payroll impact rows and participate in paid/LOP days.

    This service is deliberately isolated so future weekly-off, roster, shift,
    biometric lock, and location calendar rules can be added without touching
    salary component calculation.
    """

    def __init__(self, organization, month, year):
        self.organization = organization
        self.month = int(month)
        self.year = int(year)
        self.period_start = date(self.year, self.month, 1)
        self.period_end = date(
            self.year,
            self.month,
            calendar.monthrange(self.year, self.month)[1],
        )
        self.holiday_dates = self._holiday_dates(self.period_start, self.period_end)
        self.working_dates = self._working_dates(self.period_start, self.period_end)
        self.working_day_count = Decimal(str(len(self.working_dates))).quantize(Decimal("0.01"))

    def build(self):
        attendance_paid = self._attendance_paid_by_employee()
        leave_impacts = self._leave_impacts_by_employee()

        summaries = {}
        employee_ids = set(attendance_paid.keys()) | set(leave_impacts.keys())

        for employee_id in employee_ids:
            summaries[employee_id] = self._build_summary(
                attendance_paid.get(employee_id, ZERO),
                leave_impacts.get(employee_id, {}).get("paid", ZERO),
                leave_impacts.get(employee_id, {}).get("lop", ZERO),
            )

        return summaries

    def default_summary(self):
        return self._build_summary(ZERO, ZERO, ZERO)

    def _build_summary(self, attendance_paid_days, paid_leave_days, lop_leave_days):
        attendance_paid_days = self._clamp_days(attendance_paid_days)
        paid_leave_days = self._clamp_days(paid_leave_days)
        lop_leave_days = self._clamp_days(lop_leave_days)

        if self.working_day_count <= ZERO:
            return PayrollDaySummary(
                working_days=ZERO,
                paid_days=ZERO,
                lop_days=ZERO,
                attendance_paid_days=ZERO,
                paid_leave_days=ZERO,
                lop_leave_days=ZERO,
                absence_lop_days=ZERO,
                holidays=len(self.holiday_dates),
            )

        accounted_days = attendance_paid_days + paid_leave_days + lop_leave_days
        absence_lop_days = max(self.working_day_count - accounted_days, ZERO)
        total_lop_days = min(lop_leave_days + absence_lop_days, self.working_day_count)
        paid_days = max(self.working_day_count - total_lop_days, ZERO)

        return PayrollDaySummary(
            working_days=self.working_day_count,
            paid_days=self._money_days(paid_days),
            lop_days=self._money_days(total_lop_days),
            attendance_paid_days=self._money_days(attendance_paid_days),
            paid_leave_days=self._money_days(paid_leave_days),
            lop_leave_days=self._money_days(lop_leave_days),
            absence_lop_days=self._money_days(absence_lop_days),
            holidays=len(self.holiday_dates),
        )

    def _attendance_paid_by_employee(self):
        rows = (
            Attendance.objects.filter(
                employee__organization=self.organization,
                date__range=(self.period_start, self.period_end),
                date__in=self.working_dates,
            )
            .filter(
                Q(status__is_attendance_counted=True)
                | Q(status__isnull=True, clock_in__isnull=False)
            )
            .select_related("status")
            .values("employee_id", "date", "status_id", "status__payable_day_value")
        )

        day_values = {}
        for row in rows:
            employee_id = row["employee_id"]
            attendance_date = row["date"]
            # Legacy/manual punch rows may not have an AttendanceStatus. If a
            # clock-in exists and no status was set, count it as a full paid day.
            payable = ONE if not row["status_id"] else self._money_days(row["status__payable_day_value"] or ZERO)
            payable = max(min(payable, ONE), ZERO)
            key = (employee_id, attendance_date)
            day_values[key] = max(day_values.get(key, ZERO), payable)

        paid_by_employee = defaultdict(lambda: ZERO)
        for (employee_id, _attendance_date), payable in day_values.items():
            paid_by_employee[employee_id] += payable

        return {employee_id: self._clamp_days(value) for employee_id, value in paid_by_employee.items()}

    def _leave_impacts_by_employee(self):
        self._sync_leave_payroll_impacts()

        impacts = LeavePayrollImpact.objects.filter(
            employee__organization=self.organization,
            month=self.month,
            year=self.year,
            status__in=["PENDING", "POSTED", "ADJUSTED"],
        ).values("employee_id", "paid_leave_days", "lop_days")

        impact_by_employee = defaultdict(lambda: {"paid": ZERO, "lop": ZERO})
        for impact in impacts:
            employee_id = impact["employee_id"]
            impact_by_employee[employee_id]["paid"] += self._money_days(impact["paid_leave_days"])
            impact_by_employee[employee_id]["lop"] += self._money_days(impact["lop_days"])

        return {
            employee_id: {
                "paid": self._clamp_days(values["paid"]),
                "lop": self._clamp_days(values["lop"]),
            }
            for employee_id, values in impact_by_employee.items()
        }

    def _sync_leave_payroll_impacts(self):
        approved_leaves = LeaveRequest.objects.filter(
            employee__organization=self.organization,
            status="APPROVED",
            start_date__lte=self.period_end,
            end_date__gte=self.period_start,
        ).select_related("employee", "leave_type")

        for leave_request in approved_leaves:
            paid_days, lop_days = self._leave_days_for_period(leave_request)
            if paid_days <= ZERO and lop_days <= ZERO:
                continue

            existing_impacts = LeavePayrollImpact.objects.filter(
                employee=leave_request.employee,
                leave_request=leave_request,
                month=self.month,
                year=self.year,
            )
            if existing_impacts.exists():
                existing_impacts.update(
                    organization=self.organization,
                    paid_leave_days=paid_days,
                    lop_days=lop_days,
                    status="PENDING",
                )
            else:
                LeavePayrollImpact.objects.create(
                    organization=self.organization,
                    employee=leave_request.employee,
                    leave_request=leave_request,
                    month=self.month,
                    year=self.year,
                    paid_leave_days=paid_days,
                    lop_days=lop_days,
                    status="PENDING",
                )

    def _leave_days_for_period(self, leave_request):
        total_payroll_days = self._money_days(leave_request.total_days)
        if total_payroll_days <= ZERO:
            return ZERO, ZERO

        has_enterprise_breakdown = (
            self._money_days(leave_request.payable_days) > ZERO
            or self._money_days(leave_request.lop_days) > ZERO
        )
        if has_enterprise_breakdown:
            paid_days = self._money_days(leave_request.payable_days)
            lop_days = self._money_days(leave_request.lop_days)
        elif leave_request.leave_type.is_paid:
            paid_days = total_payroll_days
            lop_days = ZERO
        else:
            paid_days = ZERO
            lop_days = total_payroll_days

        if leave_request.start_date >= self.period_start and leave_request.end_date <= self.period_end:
            return self._clamp_days(paid_days), self._clamp_days(lop_days)

        request_working_days = self._count_working_days(leave_request.start_date, leave_request.end_date)
        overlap_start = max(leave_request.start_date, self.period_start)
        overlap_end = min(leave_request.end_date, self.period_end)
        overlap_working_days = self._count_working_days(overlap_start, overlap_end)

        if request_working_days <= ZERO or overlap_working_days <= ZERO:
            return ZERO, ZERO

        ratio = overlap_working_days / request_working_days
        return self._clamp_days(paid_days * ratio), self._clamp_days(lop_days * ratio)

    def _working_dates(self, start_date, end_date):
        days = []
        current = start_date
        while current <= end_date:
            if current.weekday() != 6 and current not in self.holiday_dates:  # Mon–Sat, excluding holidays
                days.append(current)
            current += timedelta(days=1)
        return days

    def _count_working_days(self, start_date, end_date):
        if start_date > end_date:
            return ZERO
        return Decimal(str(len(self._working_dates(start_date, end_date)))).quantize(Decimal("0.01"))

    def _holiday_dates(self, start_date, end_date):
        return HolidayCalendarService.holiday_dates_for_period(
            organization=self.organization,
            start_date=start_date,
            end_date=end_date,
            include_optional=False,
            paid_only=True,
        )

    def _clamp_days(self, value):
        return min(max(self._money_days(value), ZERO), self.working_day_count)

    @staticmethod
    def _money_days(value):
        return Decimal(str(value or ZERO)).quantize(Decimal("0.01"))
