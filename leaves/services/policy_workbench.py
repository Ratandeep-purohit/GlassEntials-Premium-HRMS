from django.utils.dateparse import parse_date

from employees.models import Department, Designation
from leaves.models import (
    LeaveAccrualRule,
    LeaveCarryForwardRule,
    LeaveCategory,
    LeaveDurationRule,
    LeaveEligibilityRule,
    LeaveIntegrationRule,
    LeavePolicy,
    LeaveProofRule,
    LeaveRestrictionRule,
    LeaveSandwichRule,
    LeaveType,
    LeaveWorkflow,
    LeaveWorkflowStep,
)
from .audit_service import LeaveAuditService
from .utils import as_decimal, as_int, checkbox


class LeavePolicyWorkbenchService:
    @staticmethod
    def save_from_post(*, organization, user, data, request=None):
        name = (data.get("name") or "").strip()
        code = (data.get("code") or "").strip().upper()
        if not name:
            raise ValueError("Leave name is required.")
        if not code:
            raise ValueError("Leave code is required.")

        category_name = (data.get("category_name") or "General Leave").strip()
        category_code = (data.get("category_code") or category_name[:10] or "GEN").strip().upper().replace(" ", "_")
        category, _ = LeaveCategory.objects.update_or_create(
            organization=organization,
            code=category_code,
            defaults={
                "name": category_name,
                "description": data.get("category_description", ""),
                "color": data.get("color_tag") or "#2563eb",
                "is_paid_category": checkbox(data, "is_paid"),
                "updated_by": user,
                "created_by": user,
            },
        )

        leave_type, created = LeaveType.objects.update_or_create(
            organization=organization,
            code=code,
            policy_version=as_int(data.get("policy_version"), 1),
            defaults={
                "category": category,
                "name": name,
                "description": data.get("description", ""),
                "color_tag": data.get("color_tag") or "#2563eb",
                "financial_year_start_month": as_int(data.get("financial_year_start_month"), 4),
                "effective_from": parse_date(data.get("effective_from") or "") or None,
                "effective_to": parse_date(data.get("effective_to") or "") or None,
                "status": data.get("status") or "DRAFT",
                "is_paid": checkbox(data, "is_paid"),
                "is_statutory": checkbox(data, "is_statutory"),
                "is_requestable": checkbox(data, "is_requestable"),
                "allow_negative_balance": checkbox(data, "allow_negative_balance"),
                "negative_balance_limit": as_decimal(data.get("negative_balance_limit")),
                "updated_by": user,
                "created_by": user,
            },
        )

        LeavePolicy.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "accrual_rate": as_decimal(data.get("accrual_rate")),
                "max_balance": as_decimal(data.get("max_balance")),
                "carry_forward_limit": as_decimal(data.get("carry_forward_limit")),
                "min_service_days": as_int(data.get("min_service_days")),
                "sandwich_rule": checkbox(data, "count_weekends_between_leave") or checkbox(data, "count_holidays_between_leave"),
                "requires_attachment": checkbox(data, "proof_required"),
                "attachment_threshold_days": as_int(data.get("required_after_days"), 3),
                "updated_by": user,
                "created_by": user,
            },
        )

        LeaveAccrualRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "frequency": data.get("accrual_frequency") or "MONTHLY",
                "accrual_day": as_int(data.get("accrual_day"), 1),
                "accrual_month": as_int(data.get("accrual_month"), 0) or None,
                "accrual_rate": as_decimal(data.get("accrual_rate")),
                "max_yearly_accrual": as_decimal(data.get("max_yearly_accrual")),
                "max_balance_cap": as_decimal(data.get("max_balance_cap") or data.get("max_balance")),
                "prorate_on_joining": checkbox(data, "prorate_on_joining"),
                "prorate_on_exit": checkbox(data, "prorate_on_exit"),
                "rounding_mode": data.get("rounding_mode") or "NONE",
                "enabled": checkbox(data, "accrual_enabled"),
                "updated_by": user,
                "created_by": user,
            },
        )

        LeaveCarryForwardRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "is_allowed": checkbox(data, "carry_forward_allowed"),
                "max_carry_forward_days": as_decimal(data.get("max_carry_forward_days") or data.get("carry_forward_limit")),
                "expiry_month": as_int(data.get("carry_expiry_month"), 3),
                "expiry_day": as_int(data.get("carry_expiry_day"), 31),
                "encash_remaining": checkbox(data, "encash_remaining"),
                "lapse_remaining": checkbox(data, "lapse_remaining"),
                "enabled": checkbox(data, "carry_forward_enabled"),
                "updated_by": user,
                "created_by": user,
            },
        )

        eligibility, _ = LeaveEligibilityRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "gender": data.get("eligible_gender") or "ANY",
                "employment_types": data.getlist("employment_types") if hasattr(data, "getlist") else [],
                "work_locations": [item.strip() for item in (data.get("work_locations") or "").split(",") if item.strip()],
                "min_service_days": as_int(data.get("min_service_days")),
                "probation_allowed": checkbox(data, "probation_allowed"),
                "confirmation_required": checkbox(data, "confirmation_required"),
                "employee_filter_mode": data.get("employee_filter_mode") or "ALL",
                "enabled": checkbox(data, "eligibility_enabled"),
                "updated_by": user,
                "created_by": user,
            },
        )
        eligibility.departments.set(Department.objects.filter(organization=organization, id__in=data.getlist("department_ids") if hasattr(data, "getlist") else []))
        eligibility.designations.set(Designation.objects.filter(organization=organization, id__in=data.getlist("designation_ids") if hasattr(data, "getlist") else []))

        LeaveRestrictionRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "min_duration": as_decimal(data.get("min_duration"), "0.50"),
                "max_duration": as_decimal(data.get("max_duration")),
                "max_consecutive_days": as_decimal(data.get("max_consecutive_days")),
                "min_gap_between_requests": as_int(data.get("min_gap_between_requests")),
                "max_requests_per_month": as_int(data.get("max_requests_per_month")),
                "max_requests_per_year": as_int(data.get("max_requests_per_year")),
                "backdate_allowed": checkbox(data, "backdate_allowed"),
                "max_backdate_days": as_int(data.get("max_backdate_days")),
                "future_date_allowed": checkbox(data, "future_date_allowed"),
                "max_future_days": as_int(data.get("max_future_days"), 365),
                "block_during_payroll_lock": checkbox(data, "block_during_payroll_lock"),
                "block_month_end": checkbox(data, "block_month_end"),
                "blackout_periods": [item.strip() for item in (data.get("blackout_periods") or "").splitlines() if item.strip()],
                "enabled": checkbox(data, "restriction_enabled"),
                "updated_by": user,
                "created_by": user,
            },
        )

        LeaveDurationRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "allow_full_day": checkbox(data, "allow_full_day"),
                "allow_half_day": checkbox(data, "allow_half_day"),
                "allow_hourly": checkbox(data, "allow_hourly"),
                "minimum_hourly_unit_minutes": as_int(data.get("minimum_hourly_unit_minutes"), 60),
                "maximum_hourly_duration_minutes": as_int(data.get("maximum_hourly_duration_minutes"), 480),
                "shift_aware": checkbox(data, "shift_aware"),
                "allowed_sessions": data.getlist("allowed_sessions") if hasattr(data, "getlist") else [],
                "updated_by": user,
                "created_by": user,
            },
        )

        LeaveSandwichRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "count_weekends_between_leave": checkbox(data, "count_weekends_between_leave"),
                "count_holidays_between_leave": checkbox(data, "count_holidays_between_leave"),
                "count_prefix_weekend": checkbox(data, "count_prefix_weekend"),
                "count_suffix_weekend": checkbox(data, "count_suffix_weekend"),
                "count_prefix_holiday": checkbox(data, "count_prefix_holiday"),
                "count_suffix_holiday": checkbox(data, "count_suffix_holiday"),
                "enabled": checkbox(data, "sandwich_enabled"),
                "updated_by": user,
                "created_by": user,
            },
        )

        LeaveProofRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "proof_required": checkbox(data, "proof_required"),
                "required_after_days": as_decimal(data.get("required_after_days")),
                "allowed_file_types": [item.strip().lower() for item in (data.get("allowed_file_types") or "pdf,jpg,jpeg,png").split(",") if item.strip()],
                "max_file_size_mb": as_int(data.get("max_file_size_mb"), 5),
                "requires_manual_review": checkbox(data, "requires_manual_review"),
                "reviewer_role": data.get("reviewer_role") or "HR",
                "enabled": checkbox(data, "proof_enabled"),
                "updated_by": user,
                "created_by": user,
            },
        )

        LeaveIntegrationRule.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            defaults={
                "attendance_sync_enabled": checkbox(data, "attendance_sync_enabled"),
                "prevent_attendance_conflict": checkbox(data, "prevent_attendance_conflict"),
                "adjust_late_marks": checkbox(data, "adjust_late_marks"),
                "comp_off_generation_enabled": checkbox(data, "comp_off_generation_enabled"),
                "payroll_sync_enabled": checkbox(data, "payroll_sync_enabled"),
                "generate_lop": checkbox(data, "generate_lop"),
                "negative_balance_deduction": checkbox(data, "negative_balance_deduction"),
                "enable_encashment": checkbox(data, "enable_encashment"),
                "final_settlement_encashment": checkbox(data, "final_settlement_encashment"),
                "updated_by": user,
                "created_by": user,
            },
        )

        LeavePolicyWorkbenchService._save_workflow(organization=organization, leave_type=leave_type, user=user, data=data)
        LeaveAuditService.record(
            organization=organization,
            entity=leave_type,
            action="POLICY_CREATED" if created else "POLICY_UPDATED",
            user=user,
            new_value={"code": leave_type.code, "name": leave_type.name, "version": leave_type.policy_version},
            request=request,
        )
        return leave_type, created

    @staticmethod
    def _save_workflow(*, organization, leave_type, user, data):
        route = data.get("approval_route") or "MANAGER_HR"
        workflow, _ = LeaveWorkflow.objects.update_or_create(
            organization=organization,
            leave_type=leave_type,
            is_default=True,
            defaults={
                "name": f"{leave_type.code} Default Approval",
                "auto_approval_enabled": route == "AUTO",
                "escalation_enabled": checkbox(data, "workflow_escalation_enabled"),
                "updated_by": user,
                "created_by": user,
            },
        )
        workflow.steps.all().delete()

        routes = {
            "AUTO": [("AUTO_APPROVE", 1)],
            "MANAGER": [("REPORTING_MANAGER", 1)],
            "HR": [("HR", 1)],
            "MANAGER_HR": [("REPORTING_MANAGER", 1), ("HR", 2)],
            "DEPT_HEAD_HR": [("DEPARTMENT_HEAD", 1), ("HR", 2)],
        }
        for approver_type, order in routes.get(route, routes["MANAGER_HR"]):
            LeaveWorkflowStep.objects.create(
                organization=organization,
                workflow=workflow,
                order=order,
                approver_type=approver_type,
                approval_mode=data.get("approval_mode") or "ANY_ONE",
                sla_hours=as_int(data.get("approval_sla_hours"), 24),
                delegation_allowed=checkbox(data, "delegation_allowed"),
                created_by=user,
            )
        return workflow
