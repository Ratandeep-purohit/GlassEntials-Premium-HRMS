from django.core.management.base import BaseCommand
from leaves.models import LeaveType, LeavePolicy, Holiday, Location
from accounts.models import Organization
from django.utils import timezone
from datetime import date

class Command(BaseCommand):
    help = 'Seeds initial leave types and sample holidays for all organizations'

    def handle(self, *args, **options):
        organizations = Organization.objects.all()
        if not organizations.exists():
            self.stdout.write(self.style.WARNING('No organizations found. Please create an organization first.'))
            return

        leave_types_data = [
            {'name': 'Casual Leave', 'code': 'CL', 'is_paid': True, 'is_statutory': False, 'description': 'Short, planned or unplanned leave for personal reasons.', 'max_balance': 10.0, 'carry_forward': 0.0},
            {'name': 'Sick Leave', 'code': 'SL', 'is_paid': True, 'is_statutory': True, 'description': 'Paid time off for illness or injury.', 'max_balance': 10.0, 'carry_forward': 5.0},
            {'name': 'Earned Leave', 'code': 'EL', 'is_paid': True, 'is_statutory': True, 'description': 'Days accrued based on workdays, commonly used for longer vacations.', 'max_balance': 15.0, 'carry_forward': 15.0},
            {'name': 'Maternity Leave', 'code': 'ML', 'is_paid': True, 'is_statutory': True, 'description': 'Paid leave for expectant mothers (26 weeks).', 'max_balance': 182.0, 'carry_forward': 0.0},
            {'name': 'Paternity Leave', 'code': 'PL', 'is_paid': True, 'is_statutory': False, 'description': 'Paid time off for new fathers.', 'max_balance': 15.0, 'carry_forward': 0.0},
            {'name': 'Compensatory Off', 'code': 'COMP', 'is_paid': True, 'is_statutory': False, 'description': 'Day off provided when an employee works on a weekend or public holiday.', 'max_balance': 0.0, 'carry_forward': 0.0},
            {'name': 'Loss of Pay', 'code': 'LOP', 'is_paid': False, 'is_statutory': False, 'description': 'Taken when an employee has no accrued paid leave left.', 'max_balance': 0.0, 'carry_forward': 0.0},
            {'name': 'Bereavement Leave', 'code': 'BL', 'is_paid': True, 'is_statutory': False, 'description': 'Paid time off due to the death of a close family member.', 'max_balance': 5.0, 'carry_forward': 0.0},
            {'name': 'Sabbatical Leave', 'code': 'SAB', 'is_paid': False, 'is_statutory': False, 'description': 'Long-term break for personal development or study.', 'max_balance': 0.0, 'carry_forward': 0.0},
            {'name': 'Marriage Leave', 'code': 'MAR', 'is_paid': True, 'is_statutory': False, 'description': 'Special leave granted for an employee’s own wedding.', 'max_balance': 5.0, 'carry_forward': 0.0},
            {'name': 'Short Leave', 'code': 'SHL', 'is_paid': True, 'is_statutory': False, 'description': '2-hour permission for personal errands. Limited to twice per month.', 'max_balance': 2.0, 'carry_forward': 0.0},
            {'name': 'Restricted Holiday', 'code': 'RH', 'is_paid': True, 'is_statutory': False, 'description': 'Optional holidays that can be claimed (Max 2 per year).', 'max_balance': 2.0, 'carry_forward': 0.0},
        ]


        holidays_data = [
            {'name': 'New Year Day', 'date': date(2026, 1, 1), 'is_optional': False},
            {'name': 'Republic Day', 'date': date(2026, 1, 26), 'is_optional': False},
            {'name': 'Holi', 'date': date(2026, 3, 14), 'is_optional': False},
            {'name': 'Good Friday', 'date': date(2026, 4, 3), 'is_optional': False},
            {'name': 'Eid-ul-Fitr', 'date': date(2026, 4, 10), 'is_optional': False},
            {'name': 'Independence Day', 'date': date(2026, 8, 15), 'is_optional': False},
            {'name': 'Gandhi Jayanti', 'date': date(2026, 10, 2), 'is_optional': False},
            {'name': 'Dussehra', 'date': date(2026, 10, 21), 'is_optional': False},
            {'name': 'Diwali', 'date': date(2026, 11, 8), 'is_optional': False},
            {'name': 'Christmas', 'date': date(2026, 12, 25), 'is_optional': False},
            # Optional Holidays (RH)
            {'name': 'Lohri', 'date': date(2026, 1, 13), 'is_optional': True},
            {'name': 'Makar Sankranti', 'date': date(2026, 1, 14), 'is_optional': True},
            {'name': 'Guru Nanak Birthday', 'date': date(2026, 11, 24), 'is_optional': True},
            {'name': 'Karaka Chaturthi (Karwa Chauth)', 'date': date(2026, 10, 29), 'is_optional': True},
            {'name': 'Govardhan Puja', 'date': date(2026, 11, 9), 'is_optional': True},
            {'name': 'Bhai Dooj', 'date': date(2026, 11, 10), 'is_optional': True},
        ]


        for org in organizations:
            self.stdout.write(f'Seeding data for organization: {org.name}')
            
            # Create a default location if none exists
            location, _ = Location.objects.get_or_create(
                organization=org,
                name='Headquarters',
                defaults={'country_code': 'IN', 'timezone': 'Asia/Kolkata'}
            )

            # Seed Leave Types
            for lt_data in leave_types_data:
                lt, created = LeaveType.objects.update_or_create(
                    organization=org,
                    code=lt_data['code'],
                    defaults={
                        'name': lt_data['name'],
                        'is_paid': lt_data['is_paid'],
                        'is_statutory': lt_data['is_statutory'],
                        'description': lt_data['description']
                    }
                )
                
                # Create or update policy for this leave type
                LeavePolicy.objects.update_or_create(
                    organization=org,
                    leave_type=lt,
                    defaults={
                        'accrual_rate': lt_data['max_balance'] / 12.0 if lt_data['max_balance'] > 0 else 0.0,
                        'max_balance': lt_data['max_balance'],
                        'carry_forward_limit': lt_data['carry_forward'],
                        'min_service_days': 0,
                        'sandwich_rule': False
                    }
                )
                self.stdout.write(f'  Processed Leave Type: {lt.name}')

            # Seed Holidays
            for h_data in holidays_data:
                holiday, created = Holiday.objects.update_or_create(
                    organization=org,
                    name=h_data['name'],
                    date=h_data['date'],
                    defaults={
                        'location_fk': location,
                        'is_optional': h_data.get('is_optional', False)
                    }
                )
                if created:
                    self.stdout.write(f'  Created Holiday: {holiday.name} ({holiday.date})')


        self.stdout.write(self.style.SUCCESS('Successfully seeded leave data.'))

