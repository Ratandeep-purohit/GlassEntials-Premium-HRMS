from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from leaves.models import LeaveBalance, LeaveTransaction, LeaveAccrualLog


class LeaveBalanceEngine:
    @staticmethod
    def get_or_create_balance(*, employee, leave_type, year, organization, user=None):
        balance, _ = LeaveBalance.objects.select_for_update().get_or_create(
            employee=employee,
            leave_type=leave_type,
            year=year,
            defaults={
                "organization": organization,
                "current_balance": Decimal("0.00"),
                "used_balance": Decimal("0.00"),
                "pending_balance": Decimal("0.00"),
                "opening_balance": Decimal("0.00"),
                "accrued_balance": Decimal("0.00"),
                "carry_forward_balance": Decimal("0.00"),
                "expired_balance": Decimal("0.00"),
                "encashed_balance": Decimal("0.00"),
                "adjusted_balance": Decimal("0.00"),
                "future_approved_balance": Decimal("0.00"),
                "created_by": user,
            },
        )
        if not balance.organization:
            balance.organization = organization
            balance.save(update_fields=["organization"])
        return balance

    @staticmethod
    @transaction.atomic
    def adjust(*, employee, leave_type, year, amount, organization, user=None, source="ADMIN", description=""):
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        balance = LeaveBalanceEngine.get_or_create_balance(
            employee=employee,
            leave_type=leave_type,
            year=year,
            organization=organization,
            user=user,
        )
        before = Decimal(str(balance.current_balance or 0)).quantize(Decimal("0.01"))
        balance.current_balance = before + amount
        balance.adjusted_balance = Decimal(str(balance.adjusted_balance or 0)).quantize(Decimal("0.01")) + amount
        balance.last_recalculated_at = timezone.now()
        balance.updated_by = user
        balance.save()

        LeaveTransaction.objects.create(
            organization=organization,
            employee=employee,
            leave_type=leave_type,
            transaction_type="ADJUSTMENT",
            amount=amount,
            balance_before=before,
            balance_after=balance.current_balance,
            effective_date=timezone.now().date(),
            source=source,
            description=description,
            created_by=user,
        )
        LeaveAccrualLog.objects.create(
            organization=organization,
            employee=employee,
            leave_type=leave_type,
            amount=amount,
            action_type="MANUAL",
            description=description,
            created_by=user,
        )
        return balance

    @staticmethod
    @transaction.atomic
    def set_balance(*, employee, leave_type, year, amount, organization, user=None, source="ADMIN", description=""):
        amount = Decimal(str(amount)).quantize(Decimal("0.01"))
        balance = LeaveBalanceEngine.get_or_create_balance(
            employee=employee,
            leave_type=leave_type,
            year=year,
            organization=organization,
            user=user,
        )
        before = Decimal(str(balance.current_balance or 0)).quantize(Decimal("0.01"))
        delta = amount - before
        balance.current_balance = amount
        balance.opening_balance = amount
        balance.adjusted_balance = Decimal(str(balance.adjusted_balance or 0)).quantize(Decimal("0.01")) + delta
        balance.last_recalculated_at = timezone.now()
        balance.updated_by = user
        balance.save()

        LeaveTransaction.objects.create(
            organization=organization,
            employee=employee,
            leave_type=leave_type,
            transaction_type="OPENING",
            amount=delta,
            balance_before=before,
            balance_after=balance.current_balance,
            effective_date=timezone.now().date(),
            source=source,
            description=description,
            created_by=user,
        )
        LeaveAccrualLog.objects.create(
            organization=organization,
            employee=employee,
            leave_type=leave_type,
            amount=delta,
            action_type="MANUAL",
            description=description,
            created_by=user,
        )
        return balance

    @staticmethod
    @transaction.atomic
    def reserve(*, leave_request, user=None):
        balance = LeaveBalanceEngine.get_or_create_balance(
            employee=leave_request.employee,
            leave_type=leave_request.leave_type,
            year=leave_request.start_date.year,
            organization=leave_request.organization,
            user=user,
        )
        before = Decimal(str(balance.current_balance or 0)).quantize(Decimal("0.01")) - Decimal(str(balance.pending_balance or 0)).quantize(Decimal("0.01"))
        amount = Decimal(str(leave_request.total_days)).quantize(Decimal("0.01"))
        balance.pending_balance = Decimal(str(balance.pending_balance or 0)).quantize(Decimal("0.01")) + amount
        balance.last_recalculated_at = timezone.now()
        balance.save()
        LeaveTransaction.objects.create(
            organization=leave_request.organization,
            employee=leave_request.employee,
            leave_type=leave_request.leave_type,
            leave_request=leave_request,
            transaction_type="RESERVE",
            amount=amount,
            balance_before=before,
            balance_after=balance.current_balance - balance.pending_balance,
            effective_date=timezone.now().date(),
            source="EMPLOYEE",
            description=f"Reserved for leave request {leave_request.id}",
            created_by=user,
        )
        return balance

    @staticmethod
    @transaction.atomic
    def consume(*, leave_request, user=None):
        balance = LeaveBalanceEngine.get_or_create_balance(
            employee=leave_request.employee,
            leave_type=leave_request.leave_type,
            year=leave_request.start_date.year,
            organization=leave_request.organization,
            user=user,
        )
        amount = Decimal(str(leave_request.total_days)).quantize(Decimal("0.01"))
        before = Decimal(str(balance.current_balance or 0)).quantize(Decimal("0.01"))
        balance.current_balance = before - amount
        balance.used_balance = Decimal(str(balance.used_balance or 0)).quantize(Decimal("0.01")) + amount
        balance.pending_balance = max(Decimal("0.00"), Decimal(str(balance.pending_balance or 0)).quantize(Decimal("0.01")) - amount)
        balance.last_recalculated_at = timezone.now()
        balance.save()
        LeaveTransaction.objects.create(
            organization=leave_request.organization,
            employee=leave_request.employee,
            leave_type=leave_request.leave_type,
            leave_request=leave_request,
            transaction_type="CONSUME",
            amount=-amount,
            balance_before=before,
            balance_after=balance.current_balance,
            effective_date=timezone.now().date(),
            source="SYSTEM",
            description=f"Consumed after approval for leave request {leave_request.id}",
            created_by=user,
        )
        return balance

    @staticmethod
    @transaction.atomic
    def release(*, leave_request, user=None, description="Released reserved leave"):
        balance = LeaveBalanceEngine.get_or_create_balance(
            employee=leave_request.employee,
            leave_type=leave_request.leave_type,
            year=leave_request.start_date.year,
            organization=leave_request.organization,
            user=user,
        )
        amount = Decimal(str(leave_request.total_days)).quantize(Decimal("0.01"))
        before = Decimal(str(balance.current_balance or 0)).quantize(Decimal("0.01")) - Decimal(str(balance.pending_balance or 0)).quantize(Decimal("0.01"))
        balance.pending_balance = max(Decimal("0.00"), Decimal(str(balance.pending_balance or 0)).quantize(Decimal("0.01")) - amount)
        balance.last_recalculated_at = timezone.now()
        balance.save()
        LeaveTransaction.objects.create(
            organization=leave_request.organization,
            employee=leave_request.employee,
            leave_type=leave_request.leave_type,
            leave_request=leave_request,
            transaction_type="RELEASE",
            amount=amount,
            balance_before=before,
            balance_after=balance.current_balance - balance.pending_balance,
            effective_date=timezone.now().date(),
            source="SYSTEM",
            description=description,
            created_by=user,
        )
        return balance
