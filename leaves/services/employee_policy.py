from decimal import Decimal

from .eligibility_engine import LeaveEligibilityEngine


class EmployeeLeavePolicyPresenter:
    @staticmethod
    def build_cards(*, employee, balances):
        cards = []
        for balance in balances:
            leave_type = balance.leave_type
            if not leave_type.category_id:
                continue
            eligibility = LeaveEligibilityEngine.evaluate(employee=employee, leave_type=leave_type)

            available = Decimal(str(balance.current_balance or 0)) - Decimal(str(balance.pending_balance or 0))
            accrual = getattr(leave_type, "accrual_rule", None)
            carry = getattr(leave_type, "carry_forward_rule", None)
            restriction = getattr(leave_type, "restriction_rule", None)
            duration = getattr(leave_type, "duration_rule", None)
            proof = getattr(leave_type, "proof_rule", None)
            integration = getattr(leave_type, "integration_rule", None)
            workflow = leave_type.enterprise_workflows.filter(is_active=True).prefetch_related("steps").first()

            cards.append({
                "balance": balance,
                "leave_type": leave_type,
                "available": available,
                "eligibility": eligibility,
                "accrual": accrual,
                "carry": carry,
                "restriction": restriction,
                "duration": duration,
                "proof": proof,
                "integration": integration,
                "workflow": workflow,
                "workflow_steps": workflow.steps.all() if workflow else [],
            })
        return cards
