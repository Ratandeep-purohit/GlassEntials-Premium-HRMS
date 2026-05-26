from django.utils import timezone


class LeaveEligibilityEngine:
    @staticmethod
    def evaluate(*, employee, leave_type, on_date=None):
        on_date = on_date or timezone.now().date()
        errors = []
        warnings = []

        if leave_type.status != "ACTIVE":
            errors.append("This leave policy is not active.")
        if not leave_type.is_active or not leave_type.is_requestable:
            errors.append("This leave policy is not requestable.")
        if leave_type.effective_from and leave_type.effective_from > on_date:
            errors.append("This leave policy is not effective yet.")
        if leave_type.effective_to and leave_type.effective_to < on_date:
            errors.append("This leave policy has expired.")

        rule = getattr(leave_type, "eligibility_rule", None)
        if not rule or not rule.enabled:
            return {
                "eligible": not errors,
                "errors": errors,
                "warnings": warnings,
            }

        if rule.gender != "ANY" and employee.gender != rule.gender:
            errors.append(f"Only {rule.gender} employees are eligible.")

        if rule.departments.exists() and employee.department_id not in rule.departments.values_list("id", flat=True):
            errors.append("Your department is not eligible for this leave policy.")

        if rule.designations.exists() and employee.designation_id not in rule.designations.values_list("id", flat=True):
            errors.append("Your designation is not eligible for this leave policy.")

        if rule.employment_types and employee.employment_type not in rule.employment_types:
            errors.append("Your employment type is not eligible for this leave policy.")

        if rule.work_locations and employee.work_location and employee.work_location not in rule.work_locations:
            errors.append("Your work location is not eligible for this leave policy.")

        if employee.joining_date:
            service_days = (on_date - employee.joining_date).days
            if service_days < rule.min_service_days:
                errors.append(f"Minimum service requirement is {rule.min_service_days} days.")
        elif rule.min_service_days:
            warnings.append("Joining date is missing, so service-day eligibility cannot be fully verified.")

        if rule.employee_filter_mode == "INCLUDE" and not rule.specific_employees.filter(pk=employee.pk).exists():
            errors.append("You are not included in this leave policy.")
        if rule.employee_filter_mode == "EXCLUDE" and rule.specific_employees.filter(pk=employee.pk).exists():
            errors.append("You are excluded from this leave policy.")

        if rule.confirmation_required:
            warnings.append("Confirmation-status validation is configured but employee confirmation data is not available yet.")
        if not rule.probation_allowed:
            warnings.append("Probation restriction is configured; probation status data is not available yet.")

        return {
            "eligible": not errors,
            "errors": errors,
            "warnings": warnings,
        }
