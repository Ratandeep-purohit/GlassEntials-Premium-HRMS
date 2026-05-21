"""
Indian Income Tax Calculator Engine (FY 2024-25)
=================================================
Calculates projected annual tax and monthly TDS based on dynamic, database-driven rules.
Supports both Old and New Tax Regimes, standard deductions, HRA exemption rules, and capped deductions.
"""

from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Q
from ..models import (
    EmployeeTaxProfile, TaxRegime, TaxSlab, TaxDeclarationCategory, EmployeeTaxDeclaration
)

def round_dec(val):
    if val is None:
        return Decimal("0.00")
    return Decimal(val).quantize(Decimal("0"), rounding=ROUND_HALF_UP)

class TaxCalculatorEngine:

    @classmethod
    def calculate_tax(cls, profile: EmployeeTaxProfile, regime: TaxRegime = None, use_approved=False) -> dict:
        """
        Calculate dynamic annual tax and recommended monthly TDS for an employee tax profile.
        
        Args:
            profile: EmployeeTaxProfile instance
            regime: TaxRegime instance. If None, uses profile.selected_regime
            use_approved: If True, uses approved_amount. If False, uses declared_amount
        """
        if not regime:
            regime = profile.selected_regime

        if not regime:
            raise ValueError(f"No tax regime selected or provided for employee {profile.employee}")

        # 1. Gross Income Calculation
        basic_salary = profile.basic_salary
        hra = profile.hra
        special_allowance = profile.special_allowance
        variable_pay = profile.variable_pay
        bonus = profile.bonus
        prev_employer_income = profile.prev_employer_income
        other_income = profile.other_income

        gross = basic_salary + hra + special_allowance + variable_pay + bonus + prev_employer_income + other_income
        if gross == Decimal("0.00") and profile.annual_ctc > Decimal("0.00"):
            # Fallback to annual CTC if no detailed breakup is provided
            gross = profile.annual_ctc

        taxable_income = gross

        # 2. Less: Standard Deduction (stored on the regime, standard is ₹50,000)
        standard_deduction = regime.standard_deduction
        taxable_income -= standard_deduction

        # 3. Exemptions & Deductions (Old Regime specific or regime-dependent)
        hra_exemption = Decimal("0.00")
        deductions_breakdown = {}
        total_deductions = Decimal("0.00")

        # Fetch declarations for this profile
        declarations = EmployeeTaxDeclaration.objects.filter(tax_profile=profile)

        if regime.regime_type == "OLD":
            # HRA Exemption Engine
            if profile.rent_paid > Decimal("0.00") and basic_salary > Decimal("0.00"):
                # Metro rule: 50% basic, Non-Metro: 40% basic
                pct = Decimal("0.50") if profile.city_type == "METRO" else Decimal("0.40")
                limit_1 = hra  # Actual HRA received
                limit_2 = profile.rent_paid - (Decimal("0.10") * basic_salary)  # Rent paid over 10% basic
                limit_3 = pct * basic_salary  # 40% or 50% basic
                
                hra_exemption = max(Decimal("0.00"), min(limit_1, limit_2, limit_3))
                hra_exemption = round_dec(hra_exemption)
                deductions_breakdown["HRA_EXEMPTION"] = float(hra_exemption)
                total_deductions += hra_exemption

            # Process database-driven declarations
            for decl in declarations:
                cat = decl.category
                # Deductions only allowed if applicable to OLD or BOTH regimes
                if cat.applicable_regime in [TaxDeclarationCategory.ApplicableRegime.OLD, TaxDeclarationCategory.ApplicableRegime.BOTH]:
                    amount = decl.approved_amount if use_approved else decl.declared_amount
                    
                    # Apply category cap if configured
                    if cat.max_limit is not None and cat.max_limit > Decimal("0.00"):
                        amount = min(amount, cat.max_limit)
                    
                    amount = round_dec(amount)
                    if amount > Decimal("0.00"):
                        deductions_breakdown[cat.code] = float(amount)
                        total_deductions += amount

            taxable_income -= total_deductions

        else:
            # New Regime allows only certain deductions (BOTH regimes, e.g. OTHER_INCOME/PREV_EMPLOYER if configured)
            for decl in declarations:
                cat = decl.category
                if cat.applicable_regime == TaxDeclarationCategory.ApplicableRegime.BOTH:
                    amount = decl.approved_amount if use_approved else decl.declared_amount
                    
                    if cat.max_limit is not None and cat.max_limit > Decimal("0.00"):
                        amount = min(amount, cat.max_limit)
                    
                    amount = round_dec(amount)
                    if amount > Decimal("0.00"):
                        deductions_breakdown[cat.code] = float(amount)
                        # Prev Employer Income is added to gross, not subtracted. But here we handle actual declarations:
                        # e.g., if there's other deductions allowed. Usually none under New Regime.
                        # Wait, PREV_EMPLOYER is handled via profile fields, but if it is in declarations, let's treat it correctly.
                        if cat.code not in ["PREV_EMPLOYER", "OTHER_INCOME"]:
                            total_deductions += amount
            
            taxable_income -= total_deductions

        taxable_income = max(Decimal("0.00"), taxable_income)
        taxable_income = round_dec(taxable_income)

        # 4. Compute Slab Tax
        computed_tax = Decimal("0.00")
        slabs = list(regime.slabs.all().order_by("min_income"))
        
        # Calculate slab-by-slab tax
        remaining_taxable = taxable_income
        for i, slab in enumerate(slabs):
            if remaining_taxable <= Decimal("0.00"):
                break
                
            min_inc = slab.min_income
            max_inc = slab.max_income
            rate = slab.tax_rate / Decimal("100.00")
            
            if max_inc is None:
                # Topmost slab (e.g. above 15L or 10L)
                if taxable_income > min_inc:
                    chunk = taxable_income - min_inc
                    computed_tax += chunk * rate
            else:
                # Intermediate slab
                if taxable_income > min_inc:
                    chunk = min(taxable_income - min_inc, max_inc - min_inc)
                    computed_tax += chunk * rate

        # 5. Apply Rebate u/s 87A
        rebate = Decimal("0.00")
        if taxable_income <= regime.rebate_limit:
            rebate = min(computed_tax, regime.rebate_max_amount)
            computed_tax -= rebate

        # 6. Apply Health & Education Cess (4%)
        cess = round_dec(computed_tax * Decimal("0.04"))
        total_tax_liability = computed_tax + cess

        # 7. Recommended Monthly TDS
        monthly_tds = round_dec(total_tax_liability / Decimal("12.00"))

        return {
            "gross_income": float(gross),
            "taxable_income": float(taxable_income),
            "standard_deduction": float(standard_deduction),
            "hra_exemption": float(hra_exemption),
            "total_deductions": float(total_deductions),
            "deductions_breakdown": deductions_breakdown,
            "computed_tax": float(computed_tax),
            "rebate_87a": float(rebate),
            "cess": float(cess),
            "total_tax_liability": float(total_tax_liability),
            "monthly_tds": float(monthly_tds),
            "regime_name": str(regime),
            "regime_type": regime.regime_type
        }

