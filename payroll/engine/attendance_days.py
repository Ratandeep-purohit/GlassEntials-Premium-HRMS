import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
import logging

from django.db.models import Q

from attendance.models import Attendance
from leaves.models import LeavePayrollImpact, LeaveRequest
from leaves.services.holiday_calendar_service import HolidayCalendarService
from leaves.services.calendar_engine import (
    _get_org_sandwich_policy,
    _get_weekly_off_days,
)

logger = logging.getLogger(__name__)

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
    sandwich_lop_days: Decimal   # weekly offs counted as LOP due to Sandwich Leave Policy
    holidays: int

    @property
    def remarks(self):
        base = (
            f"Working days: {self.working_days}; "
            f"Attendance paid: {self.attendance_paid_days}; "
            f"Paid leave: {self.paid_leave_days}; "
            f"LOP leave: {self.lop_leave_days}; "
            f"Absent LOP: {self.absence_lop_days}"
        )
        if self.sandwich_lop_days > ZERO:
            base += f"; Sandwich LOP: {self.sandwich_lop_days}"
        return base


class PayrollAttendanceService:
    """
    Calculates payroll-ready paid/LOP days.

    Current enterprise baseline:
    - Monday-Saturday are payable work days (Sunday is weekly off).
    - Paid, non-optional holidays reduce payable work days.
    - AttendanceStatus.payable_day_value supports present/half-day/paid statuses.
    - Approved leaves create payroll impact rows and participate in paid/LOP days.
    - When the org's Sandwich Leave Policy is ON, weekly offs sandwiched between
      absent working days are counted as additional LOP days for that employee.

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
        # Sandwich Leave Policy — must be set BEFORE _working_dates() is called
        self.sandwich_policy = _get_org_sandwich_policy(organization)
        self.weekly_off_days = _get_weekly_off_days(organization)

        total_calendar_days = (self.period_end - self.period_start).days + 1
        all_period_dates = [self.period_start + timedelta(days=i) for i in range(total_calendar_days)]

        self.weekly_off_dates = {d for d in all_period_dates if d.weekday() in self.weekly_off_days}
        self.holiday_dates = set(self._holiday_dates(self.period_start, self.period_end))
        self.combined_non_working_dates = self.weekly_off_dates | self.holiday_dates
        self.working_dates = [d for d in all_period_dates if d not in self.combined_non_working_dates]
        self.working_day_count = Decimal(str(len(self.working_dates))).quantize(Decimal("0.01"))

        # Explicit debug log for working days breakdown
        logger.info(
            "Payroll period %s to %s debug:\n"
            "Total calendar days: %d\n"
            "Weekly off dates: %d\n"
            "Applicable paid holiday dates: %d\n"
            "Combined non-working dates: %d\n"
            "Final working days: %s",
            self.period_start,
            self.period_end,
            total_calendar_days,
            len(self.weekly_off_dates),
            len(self.holiday_dates),
            len(self.combined_non_working_dates),
            self.working_day_count,
        )

    def build(self):
        per_day_values = self._attendance_per_day_values()
        attendance_paid = self._aggregate_attendance_paid(per_day_values)
        sandwich_extra = self._sandwich_absent_extra_by_employee(per_day_values)
        leave_impacts = self._leave_impacts_by_employee()

        summaries = {}
        employee_ids = (
            set(attendance_paid.keys())
            | set(leave_impacts.keys())
            | set(sandwich_extra.keys())
        )

        from employees.models import Employee
        employee_map = {
            emp.id: emp
            for emp in Employee.objects.filter(
                organization=self.organization,
                id__in=employee_ids,
            ).only("id", "work_location")
        }

        for employee_id in employee_ids:
            summaries[employee_id] = self._build_summary(
                attendance_paid.get(employee_id, ZERO),
                leave_impacts.get(employee_id, {}).get("paid", ZERO),
                leave_impacts.get(employee_id, {}).get("lop", ZERO),
                sandwich_lop_days=self._money_days(sandwich_extra.get(employee_id, 0)),
                employee=employee_map.get(employee_id),
            )

        return summaries

    def default_summary(self, employee=None):
        return self._build_summary(ZERO, ZERO, ZERO, employee=employee)

    def _build_summary(self, attendance_paid_days, paid_leave_days, lop_leave_days,
                       sandwich_lop_days=ZERO, employee=None):
        working_day_count = self.working_day_count
        holiday_count = len(self.holiday_dates)

        if employee and (getattr(employee, "work_location", "") or "").strip():
            emp_holidays = set(self._holiday_dates(self.period_start, self.period_end, employee=employee))
            if emp_holidays != self.holiday_dates:
                emp_non_working = self.weekly_off_dates | emp_holidays
                total_calendar_days = (self.period_end - self.period_start).days + 1
                working_day_count = Decimal(str(total_calendar_days - len(emp_non_working))).quantize(Decimal("0.01"))
                holiday_count = len(emp_holidays)

        attendance_paid_days = self._clamp_days(attendance_paid_days, working_day_count)
        paid_leave_days = self._clamp_days(paid_leave_days, working_day_count)
        lop_leave_days = self._clamp_days(lop_leave_days, working_day_count)
        sandwich_lop_days = self._money_days(sandwich_lop_days)

        if working_day_count <= ZERO:
            return PayrollDaySummary(
                working_days=ZERO,
                paid_days=ZERO,
                lop_days=ZERO,
                attendance_paid_days=ZERO,
                paid_leave_days=ZERO,
                lop_leave_days=ZERO,
                absence_lop_days=ZERO,
                sandwich_lop_days=ZERO,
                holidays=holiday_count,
            )

        accounted_days = attendance_paid_days + paid_leave_days + lop_leave_days
        absence_lop_days = max(working_day_count - accounted_days, ZERO)

        # Sandwich LOP days are extra deductions beyond working_day_count.
        # They reduce paid_days directly without changing working_day_count itself,
        # so all salary formulas that reference lop_days automatically pick them up.
        total_lop_days = min(
            lop_leave_days + absence_lop_days + sandwich_lop_days,
            working_day_count + sandwich_lop_days,
        )
        paid_days = max(working_day_count - lop_leave_days - absence_lop_days, ZERO)
        # sandwich days reduce paid_days further (cannot go below zero)
        paid_days = max(paid_days - sandwich_lop_days, ZERO)

        return PayrollDaySummary(
            working_days=working_day_count,
            paid_days=self._money_days(paid_days),
            lop_days=self._money_days(total_lop_days),
            attendance_paid_days=self._money_days(attendance_paid_days),
            paid_leave_days=self._money_days(paid_leave_days),
            lop_leave_days=self._money_days(lop_leave_days),
            absence_lop_days=self._money_days(absence_lop_days),
            sandwich_lop_days=self._money_days(sandwich_lop_days),
            holidays=holiday_count,
        )

    # ── Attendance per-day values ────────────────────────────────────────────

    def _attendance_per_day_values(self):
        """
        Returns {(employee_id, date): payable_value} for all attendance rows
        in this period that fall on a working date.
        """
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
            .values(
                "employee_id", "date", "status_id",
                "status__payable_day_value", "net_work_hours",
                "clock_in", "clock_out",
            )
        )

        day_values = {}
        for row in rows:
            employee_id = row["employee_id"]
            attendance_date = row["date"]

            if row["status_id"]:
                payable = self._money_days(row["status__payable_day_value"] or ZERO)
            else:
                net_hours = row.get("net_work_hours")
                if net_hours is None and row.get("clock_in") and row.get("clock_out"):
                    import datetime
                    t1 = datetime.datetime.combine(attendance_date, row.get("clock_in"))
                    t2 = datetime.datetime.combine(attendance_date, row.get("clock_out"))
                    net_hours = (t2 - t1).total_seconds() / 3600.0

                if net_hours is not None:
                    if 3 <= float(net_hours) < 7:
                        payable = Decimal("0.5")
                    elif float(net_hours) < 3:
                        payable = ZERO
                    else:
                        payable = ONE
                else:
                    payable = ONE if row.get("clock_in") else ZERO

            payable = max(min(payable, ONE), ZERO)
            key = (employee_id, attendance_date)
            day_values[key] = max(day_values.get(key, ZERO), payable)

        return day_values

    def _aggregate_attendance_paid(self, per_day_values):
        """Sum per-day payable values into per-employee totals."""
        paid_by_employee = defaultdict(lambda: ZERO)
        for (employee_id, _date), payable in per_day_values.items():
            paid_by_employee[employee_id] += payable
        return {
            employee_id: self._clamp_days(value)
            for employee_id, value in paid_by_employee.items()
        }

    # Keep original method name for backward compatibility
    def _attendance_paid_by_employee(self):
        return self._aggregate_attendance_paid(self._attendance_per_day_values())

    # ── Sandwich absent detection ────────────────────────────────────────────

    def _sandwich_absent_extra_by_employee(self, per_day_values):
        """
        Sandwich Leave Policy — absence scenario.

        For each weekly off in the period, if an employee was absent (payable=0)
        on the nearest working day BEFORE the weekly off AND on the nearest working
        day AFTER the weekly off, that weekly off counts as an extra LOP day.

        Only applies when the org-level sandwich_leave_policy is ON.
        Only unauthorised absence (payable=0 on a working day) qualifies as a
        boundary day here; approved paid leave does not (it's handled separately
        by LeaveCalendarEngine so there's no double-counting).

        Returns {employee_id: int} — number of extra sandwich LOP days.
        """
        if not self.sandwich_policy:
            return {}

        # Sorted working dates for prev/next lookups
        sorted_working = sorted(self.working_dates)
        working_dates_set = set(self.working_dates)

        # Find all weekly off dates in the period (that are not paid holidays)
        weekly_off_in_period = []
        current = self.period_start
        while current <= self.period_end:
            if (
                current.weekday() in self.weekly_off_days
                and current not in self.holiday_dates
                and current not in working_dates_set
            ):
                weekly_off_in_period.append(current)
            current += timedelta(days=1)

        if not weekly_off_in_period:
            return {}

        # Build a set of (employee_id, date) pairs with payable > 0
        present_keys = {
            key for key, payable in per_day_values.items() if payable > ZERO
        }
        all_employee_ids = {eid for (eid, _) in per_day_values.keys()}

        # Also need employees that had leave impacts (they may have no attendance rows)
        # — we only care about absence (payable=0), so employees with no row are absent.

        sandwich_extra = defaultdict(int)

        for wo_date in weekly_off_in_period:
            # Find nearest working day before and after this weekly off
            prev_wd = None
            next_wd = None
            for wd in sorted_working:
                if wd < wo_date:
                    prev_wd = wd
                elif wd > wo_date and next_wd is None:
                    next_wd = wd
                    break

            if prev_wd is None or next_wd is None:
                # Weekly off at start/end of month with no working day on one side
                continue

            for employee_id in all_employee_ids:
                prev_present = (employee_id, prev_wd) in present_keys
                next_present = (employee_id, next_wd) in present_keys
                # Sandwich: absent on BOTH boundary working days
                if not prev_present and not next_present:
                    sandwich_extra[employee_id] += 1

        return dict(sandwich_extra)

    # ── Leave payroll impacts ────────────────────────────────────────────────

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

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _working_dates(self, start_date, end_date):
        days = []
        current = start_date
        while current <= end_date:
            if current.weekday() not in self.weekly_off_days and current not in self.holiday_dates:
                days.append(current)
            current += timedelta(days=1)
        return days

    def _count_working_days(self, start_date, end_date):
        if start_date > end_date:
            return ZERO
        return Decimal(str(len(self._working_dates(start_date, end_date)))).quantize(Decimal("0.01"))

    def _holiday_dates(self, start_date, end_date, employee=None):
        return HolidayCalendarService.holiday_dates_for_period(
            organization=self.organization,
            start_date=start_date,
            end_date=end_date,
            employee=employee,
            include_optional=False,
            paid_only=True,
        )

    def _clamp_days(self, value, max_days=None):
        cap = max_days if max_days is not None else self.working_day_count
        return min(max(self._money_days(value), ZERO), cap)

    @staticmethod
    def _money_days(value):
        return Decimal(str(value or ZERO)).quantize(Decimal("0.01"))
