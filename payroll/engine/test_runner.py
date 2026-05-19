from decimal import Decimal
from payroll.engine.formula_runner import evaluate_formula

def test_formulas():
    context = {
        'basic': Decimal('15000'),
        'gross': Decimal('25000'),
        'ctc': Decimal('30000')
    }
    
    test_cases = [
        ("basic * 0.12", Decimal("1800.00")),
        ("basic + (gross * 0.10)", Decimal("17500.00")),
        ("gross - basic", Decimal("10000.00")),
        ("1500", Decimal("1500.00")),
        ("basic * 0.5 / 2", Decimal("3750.00")),
    ]
    
    print("Testing Formula Runner...")
    for formula, expected in test_cases:
        result = evaluate_formula(formula, context)
        status = "PASS" if result == expected else "FAIL"
        print(f"{status} Formula: {formula} | Expected: {expected} | Got: {result}")

if __name__ == "__main__":
    test_formulas()
