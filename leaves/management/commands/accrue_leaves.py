from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db import transaction
from leaves.models import Employee, LeaveBalance, LeavePolicy, LeaveAccrualLog

class Command(BaseCommand):
    help = 'Automatically accrues leaves for all employees based on policy (runs monthly)'

    def handle(self, *args, **options):
        current_year = timezone.now().year
        today = timezone.now().date()
        
        employees = Employee.objects.all()
        processed_count = 0

        self.stdout.write(self.style.SUCCESS(f'Starting leave accrual for {today.strftime("%B %Y")}'))

        with transaction.atomic():
            for employee in employees:
                # Find policies for this employee's organization
                policies = LeavePolicy.objects.filter(organization=employee.organization)
                
                for policy in policies:
                    # Get or create balance for current year
                    balance, created = LeaveBalance.objects.get_or_create(
                        employee=employee,
                        leave_type=policy.leave_type,
                        year=current_year,
                        defaults={'current_balance': Decimal('0.0')}
                    )


                    # Accrual logic
                    accrual_amount = policy.accrual_rate
                    new_balance = balance.current_balance + accrual_amount
                    
                    # Cap at max balance
                    if new_balance > policy.max_balance:
                        accrual_amount = max(0, policy.max_balance - balance.current_balance)
                        new_balance = policy.max_balance

                    if accrual_amount > 0:
                        balance.current_balance = new_balance
                        balance.save()

                        # Log the accrual
                        LeaveAccrualLog.objects.create(
                            employee=employee,
                            leave_type=policy.leave_type,
                            amount=accrual_amount,
                            action_type='ACCRUAL',
                            description=f'Monthly automated accrual for {today.strftime("%B %Y")}',
                            organization=employee.organization
                        )
                
                processed_count += 1

        self.stdout.write(self.style.SUCCESS(f'Successfully processed accrual for {processed_count} employees.'))
