import datetime
from decimal import Decimal
from django.core.management.base import BaseCommand
from payroll.models import (
    FinancialYear, TaxRegime, TaxSlab, TaxDeclarationCategory, DeclarationCutoffPolicy
)
from accounts.models import Organization

class Command(BaseCommand):
    help = 'Populates the database with Financial Year 2024-2025 tax regimes, slabs, and default categories'

    def handle(self, *args, **options):
        self.stdout.write("Populating tax master data...")

        # 1. Create or get Financial Year
        fy, created = FinancialYear.objects.get_or_create(
            name="2024-2025",
            defaults={
                "start_date": datetime.date(2024, 4, 1),
                "end_date": datetime.date(2025, 3, 31),
                "is_active": True
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS(f"Created Financial Year: {fy.name}"))
        else:
            self.stdout.write(f"Financial Year {fy.name} already exists.")

        # 2. Create Tax Regimes
        # Old Regime
        old_regime, created = TaxRegime.objects.get_or_create(
            financial_year=fy,
            regime_type=TaxRegime.RegimeType.OLD,
            defaults={
                "standard_deduction": Decimal("50000.00"),
                "rebate_limit": Decimal("500000.00"),
                "rebate_max_amount": Decimal("12500.00")
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created Old Tax Regime"))
        else:
            self.stdout.write("Old Tax Regime already exists.")

        # New Regime
        new_regime, created = TaxRegime.objects.get_or_create(
            financial_year=fy,
            regime_type=TaxRegime.RegimeType.NEW,
            defaults={
                "standard_deduction": Decimal("50000.00"),
                "rebate_limit": Decimal("700000.00"),
                "rebate_max_amount": Decimal("25000.00")
            }
        )
        if created:
            self.stdout.write(self.style.SUCCESS("Created New Tax Regime"))
        else:
            self.stdout.write("New Tax Regime already exists.")

        # 3. Create Tax Slabs
        # Old Regime Slabs
        old_slabs = [
            (Decimal("0.00"), Decimal("250000.00"), Decimal("0.00")),
            (Decimal("250000.00"), Decimal("500000.00"), Decimal("5.00")),
            (Decimal("500000.00"), Decimal("1000000.00"), Decimal("20.00")),
            (Decimal("1000000.00"), None, Decimal("30.00")),
        ]
        for min_inc, max_inc, rate in old_slabs:
            slab, created = TaxSlab.objects.get_or_create(
                regime=old_regime,
                min_income=min_inc,
                max_income=max_inc,
                defaults={"tax_rate": rate}
            )
            if created:
                self.stdout.write(f"Created Old Slab: {min_inc} - {max_inc} @ {rate}%")

        # New Regime Slabs
        new_slabs = [
            (Decimal("0.00"), Decimal("300000.00"), Decimal("0.00")),
            (Decimal("300000.00"), Decimal("600000.00"), Decimal("5.00")),
            (Decimal("600000.00"), Decimal("900000.00"), Decimal("10.00")),
            (Decimal("900000.00"), Decimal("1200000.00"), Decimal("15.00")),
            (Decimal("1200000.00"), Decimal("1500000.00"), Decimal("20.00")),
            (Decimal("1500000.00"), None, Decimal("30.00")),
        ]
        for min_inc, max_inc, rate in new_slabs:
            slab, created = TaxSlab.objects.get_or_create(
                regime=new_regime,
                min_income=min_inc,
                max_income=max_inc,
                defaults={"tax_rate": rate}
            )
            if created:
                self.stdout.write(f"Created New Slab: {min_inc} - {max_inc} @ {rate}%")

        # 4. Create default categories
        categories = [
            {
                "code": "SEC_80C",
                "name": "Section 80C Deductions",
                "description": "PPF, LIC, ELSS Mutual Funds, EPF, etc.",
                "max_limit": Decimal("150000.00"),
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.OLD,
                "display_order": 10
            },
            {
                "code": "SEC_80D",
                "name": "Section 80D Medical Insurance",
                "description": "Health Insurance Premium for Self, Spouse, Children, and Parents.",
                "max_limit": Decimal("75000.00"),
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.OLD,
                "display_order": 20
            },
            {
                "code": "HRA",
                "name": "House Rent Allowance (HRA) Exemption",
                "description": "Exemption on house rent paid. Requires Rent Agreement or Receipts.",
                "max_limit": None,
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.OLD,
                "display_order": 30
            },
            {
                "code": "HOME_LOAN",
                "name": "Home Loan Interest (Section 24b)",
                "description": "Interest payable on housing loan for self-occupied property.",
                "max_limit": Decimal("200000.00"),
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.OLD,
                "display_order": 40
            },
            {
                "code": "SEC_80CCD_1B",
                "name": "Section 80CCD(1B) NPS",
                "description": "Additional employee contribution to National Pension System (NPS).",
                "max_limit": Decimal("50000.00"),
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.OLD,
                "display_order": 50
            },
            {
                "code": "SEC_80E",
                "name": "Section 80E Education Loan",
                "description": "Interest on education loan for self, spouse, or children.",
                "max_limit": None,
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.OLD,
                "display_order": 60
            },
            {
                "code": "SEC_80G",
                "name": "Section 80G Donations",
                "description": "Donations to specified charitable institutions or funds.",
                "max_limit": None,
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.OLD,
                "display_order": 70
            },
            {
                "code": "PREV_EMPLOYER",
                "name": "Previous Employer Income & TDS",
                "description": "Salary received and TDS deducted by previous employer during the financial year.",
                "max_limit": None,
                "is_proof_required": True,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.BOTH,
                "display_order": 80
            },
            {
                "code": "OTHER_INCOME",
                "name": "Income from Other Sources",
                "description": "Interest income, rental income, or other taxable earnings.",
                "max_limit": None,
                "is_proof_required": False,
                "applicable_regime": TaxDeclarationCategory.ApplicableRegime.BOTH,
                "display_order": 90
            }
        ]

        for cat_data in categories:
            cat, created = TaxDeclarationCategory.objects.get_or_create(
                code=cat_data["code"],
                defaults={
                    "name": cat_data["name"],
                    "description": cat_data["description"],
                    "max_limit": cat_data["max_limit"],
                    "is_proof_required": cat_data["is_proof_required"],
                    "applicable_regime": cat_data["applicable_regime"],
                    "display_order": cat_data["display_order"]
                }
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created Category: {cat.code}"))
            else:
                # Update defaults if changed
                cat.name = cat_data["name"]
                cat.description = cat_data["description"]
                cat.max_limit = cat_data["max_limit"]
                cat.is_proof_required = cat_data["is_proof_required"]
                cat.applicable_regime = cat_data["applicable_regime"]
                cat.display_order = cat_data["display_order"]
                cat.save()
                self.stdout.write(f"Updated/Verified Category: {cat.code}")

        # 5. Add default cutoff policy for current financial year
        # Create cutoff policies for all 12 months
        for month in range(1, 13):
            # Cutoff on 25th of the month
            cutoff_date = datetime.datetime(2024 if month >= 4 else 2025, month, 25, 23, 59, 59)
            policy, created = DeclarationCutoffPolicy.objects.get_or_create(
                financial_year=fy,
                month=month,
                defaults={"cutoff_date": cutoff_date}
            )
            if created:
                self.stdout.write(f"Created Cutoff Policy for Month {month}: {cutoff_date}")

        self.stdout.write(self.style.SUCCESS("Tax master data populated successfully!"))
