from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from leaves.models import LeaveRequest


class LeaveRestrictionEngine:
    @staticmethod
    def validate_application(*, employee, leave_type, start_date, end_date, session_type, total_days, attachment=None):
        errors = []
        warnings = []
        today = timezone.now().date()
        total_days = Decimal(str(total_days)).quantize(Decimal("0.01"))

        overlap_exists = LeaveRequest.objects.filter(
            employee=employee,
            status__in=["PENDING", "MANAGER_APPROVED", "APPROVED"],
            start_date__lte=end_date,
            end_date__gte=start_date,
        ).exists()
        if overlap_exists:
            errors.append("You already have a pending or approved leave in this date range.")

        duration_rule = getattr(leave_type, "duration_rule", None)
        if duration_rule:
            if session_type == "FULL" and not duration_rule.allow_full_day:
                errors.append("Full-day leave is not allowed for this policy.")
            if session_type in ["MORNING", "AFTERNOON"] and not duration_rule.allow_half_day:
                errors.append("Half-day leave is not allowed for this policy.")
            if session_type == "SHORT" and not duration_rule.allow_hourly:
                errors.append("Hourly/short leave is not allowed for this policy.")

        restriction = getattr(leave_type, "restriction_rule", None)
        if restriction and restriction.enabled:
            if total_days < restriction.min_duration:
                errors.append(f"Minimum leave duration is {restriction.min_duration} day(s).")
            if restriction.max_duration and total_days > restriction.max_duration:
                errors.append(f"Maximum leave duration is {restriction.max_duration} day(s).")
            if restriction.max_consecutive_days and total_days > restriction.max_consecutive_days:
                errors.append(f"Maximum consecutive leave allowed is {restriction.max_consecutive_days} day(s).")

            if start_date < today:
                if not restriction.backdate_allowed:
                    errors.append("Backdated leave is not allowed for this policy.")
                elif (today - start_date).days > restriction.max_backdate_days:
                    errors.append(f"Backdated leave cannot be older than {restriction.max_backdate_days} day(s).")

            if start_date > today and restriction.future_date_allowed:
                if restriction.max_future_days and (start_date - today).days > restriction.max_future_days:
                    errors.append(f"Future leave cannot be beyond {restriction.max_future_days} day(s).")
            elif start_date > today and not restriction.future_date_allowed:
                errors.append("Future leave is not allowed for this policy.")

            if restriction.max_requests_per_month:
                month_count = LeaveRequest.objects.filter(
                    employee=employee,
                    leave_type=leave_type,
                    start_date__year=start_date.year,
                    start_date__month=start_date.month,
                    status__in=["PENDING", "MANAGER_APPROVED", "APPROVED"],
                ).count()
                if month_count >= restriction.max_requests_per_month:
                    errors.append(f"Monthly request limit of {restriction.max_requests_per_month} reached.")

            if restriction.max_requests_per_year:
                year_count = LeaveRequest.objects.filter(
                    employee=employee,
                    leave_type=leave_type,
                    start_date__year=start_date.year,
                    status__in=["PENDING", "MANAGER_APPROVED", "APPROVED"],
                ).count()
                if year_count >= restriction.max_requests_per_year:
                    errors.append(f"Yearly request limit of {restriction.max_requests_per_year} reached.")

            if restriction.blackout_periods:
                for period in restriction.blackout_periods:
                    warnings.append(f"Blackout configured: {period}")

        proof_rule = getattr(leave_type, "proof_rule", None)
        if proof_rule and proof_rule.enabled and proof_rule.proof_required:
            if total_days > proof_rule.required_after_days and not attachment:
                errors.append(f"Proof is required for leave above {proof_rule.required_after_days} day(s).")

        sandwich = getattr(leave_type, "sandwich_rule_config", None)
        if sandwich and sandwich.enabled and sandwich.blocked_clubbing_leave_types.exists():
            blocked_ids = sandwich.blocked_clubbing_leave_types.values_list("id", flat=True)
            clubbing_exists = LeaveRequest.objects.filter(
                employee=employee,
                leave_type_id__in=blocked_ids,
                status__in=["PENDING", "MANAGER_APPROVED", "APPROVED"],
            ).filter(Q(end_date=start_date) | Q(start_date=end_date)).exists()
            if clubbing_exists:
                errors.append("This leave cannot be clubbed with an adjacent restricted leave policy.")

        return {
            "valid": not errors,
            "errors": errors,
            "warnings": warnings,
        }
