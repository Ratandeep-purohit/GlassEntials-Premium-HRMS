from decimal import Decimal

class StatutoryEngine:
    """
    Logic for Indian statutory deductions: PF, ESI, Professional Tax.
    """

    @staticmethod
    def calculate_epf(basic_salary, employee_rate=Decimal("0.12"), cap_limit=Decimal("15000")):
        """
        Calculate Employee Provident Fund (EPF).
        Default: 12% of Basic, capped at 15,000 basic limit.
        """
        eligible_basic = min(basic_salary, cap_limit) if cap_limit else basic_salary
        return (eligible_basic * employee_rate).quantize(Decimal("1.00"))

    @staticmethod
    def calculate_esi(gross_salary, employee_rate=Decimal("0.0075"), threshold=Decimal("21000")):
        """
        Calculate Employee State Insurance (ESI).
        Default: 0.75% of Gross, only if Gross <= 21,000.
        """
        if gross_salary > threshold:
            return Decimal("0.00")
        return (gross_salary * employee_rate).quantize(Decimal("1.00"))

    @staticmethod
    def calculate_pt(gross_salary, state="Maharashtra"):
        """
        Calculate Professional Tax (PT). 
        Generic slab-based logic (simplified Maharashtra model).
        """
        # Note: In a real system, these slabs would be in a DB model.
        if state == "Maharashtra":
            if gross_salary <= Decimal("7500"):
                return Decimal("0.00")
            elif gross_salary <= Decimal("10000"):
                return Decimal("175.00")
            else:
                # 200 for 11 months, 300 for February. Simplified to 200.
                return Decimal("200.00")
        
        # Default fallback
        return Decimal("0.00")

def calculate_statutory_deductions(basic, gross, state="Maharashtra"):
    """
    Returns a dict of statutory deductions.
    """
    return {
        "PF": StatutoryEngine.calculate_epf(basic),
        "ESI": StatutoryEngine.calculate_esi(gross),
        "PT": StatutoryEngine.calculate_pt(gross, state)
    }
