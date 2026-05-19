from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from leaves.models import Employee, LeaveBalance, LeavePolicy, LeaveAccrualLog


class Command(BaseCommand):
    help = 'Processes year-end carry forward and lapses unused leaves (runs Dec 31st)'

    def handle(self, *args, **options):
        current_year = timezone.now().year
        next_year = current_year + 1
        
        employees = Employee.objects.all()
        processed_count = 0

        self.stdout.write(self.style.SUCCESS(f'Starting Year-End processing for {current_year} -> {next_year}'))

        with transaction.atomic():
            for employee in employees:
                # Find all balances for current year
                current_balances = LeaveBalance.objects.filter(employee=employee, year=current_year)
                
                for balance in current_balances:
                    # Find policy for this leave type
                    policy = LeavePolicy.objects.filter(
                        leave_type=balance.leave_type, 
                        organization=employee.organization
                    ).first()

                    if not policy:
                        continue

                    # Calculate carry forward amount
                    carry_forward = min(balance.current_balance, policy.carry_forward_limit)
                    lapsed = balance.current_balance - carry_forward

                    # Create balance for next year
                    next_bal, created = LeaveBalance.objects.get_or_create(
                        employee=employee,
                        leave_type=balance.leave_type,
                        year=next_year,
                        defaults={'current_balance': carry_forward}
                    )


                    
                    if not created:
                        # If somehow it already existed, we add to it (or overwrite based on policy)
                        next_bal.current_balance += carry_forward
                        next_bal.save()

                    # Log carry forward
                    if carry_forward > 0:
                        LeaveAccrualLog.objects.create(
                            employee=employee,
                            leave_type=balance.leave_type,
                            amount=carry_forward,
                            action_type='CARRY_FORWARD',
                            description=f'Carry forward from {current_year}',
                            organization=employee.organization
                        )

                    # Log lapsed leaves if any
                    if lapsed > 0:
                        LeaveAccrualLog.objects.create(
                            employee=employee,
                            leave_type=balance.leave_type,
                            amount=-lapsed,
                            action_type='MANUAL', # Or add a 'LAPSED' choice
                            description=f'Leaves lapsed at end of {current_year}',
                            organization=employee.organization
                        )
                
                processed_count += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully processed year-end for {processed_count} employees.'))
