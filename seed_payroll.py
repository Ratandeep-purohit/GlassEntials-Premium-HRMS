import os
import django
from decimal import Decimal
from datetime import date

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'HRMS_Glassentials.settings')
django.setup()

from payroll.models import SalaryComponent, SalaryStructure, SalaryStructureItem, PayrollRun
from employees.models import Employee, Department, Designation
from django.contrib.auth import get_user_model

User = get_user_model()

def seed():
    print("Seeding Payroll Master Data...")

    # 1. Ensure a Department and Designation exist
    dept, _ = Department.objects.get_or_create(name="Engineering")
    desig, _ = Designation.objects.get_or_create(name="Software Engineer")

    # 2. Create a Test Employee (if none exist)
    user = User.objects.filter(username="testuser").first()
    if not user:
        user = User.objects.create_user(username="testuser", email="test@glassentials.com", password="password123")

    emp, created = Employee.objects.get_or_create(
        employee_id="GENT-001",
        defaults={
            'first_name': "John",
            'last_name': "Doe",
            'email': "test@glassentials.com",
            'department': dept,
            'designation': desig,
            'joining_date': date(2025, 1, 1),
            'is_active': True
        }
    )
    if created: print(f"Created Employee: {emp}")

    # 3. Create Basic Salary Components
    basic, _ = SalaryComponent.objects.get_or_create(
        code="BASIC",
        defaults={
            'name': "Basic Salary",
            'component_type': SalaryComponent.ComponentType.EARNING,
            'calculation_type': SalaryComponent.CalculationType.FIXED,
            'display_order': 1
        }
    )
    hra, _ = SalaryComponent.objects.get_or_create(
        code="HRA",
        defaults={
            'name': "House Rent Allowance",
            'component_type': SalaryComponent.ComponentType.EARNING,
            'calculation_type': SalaryComponent.CalculationType.FORMULA,
            'formula': "basic * 0.40",
            'display_order': 2
        }
    )
    pf, _ = SalaryComponent.objects.get_or_create(
        code="PF",
        defaults={
            'name': "Provident Fund",
            'component_type': SalaryComponent.ComponentType.DEDUCTION,
            'is_statutory': True,
            'display_order': 10
        }
    )
    print("Created Salary Components (BASIC, HRA, PF)")

    # 4. Create Salary Structure for Employee
    struct, created = SalaryStructure.objects.get_or_create(
        employee=emp,
        effective_date=date(2025, 1, 1),
        defaults={
            'ctc': Decimal("1200000"),
            'gross_salary': Decimal("100000"),
            'basic_salary': Decimal("50000"),
        }
    )
    
    if created:
        SalaryStructureItem.objects.get_or_create(salary_structure=struct, component=basic, fixed_amount=Decimal("50000"))
        SalaryStructureItem.objects.get_or_create(salary_structure=struct, component=hra) # Will use formula
        print(f"Created Salary Structure for {emp}")

    # 5. Create a Sample Loan
    from payroll.models import EmployeeLoan, LoanInstallment
    loan, created = EmployeeLoan.objects.get_or_create(
        loan_number="LN-001",
        defaults={
            'employee': emp,
            'loan_type': EmployeeLoan.LoanType.PERSONAL_LOAN,
            'principal_amount': Decimal("50000"),
            'emi_amount': Decimal("5000"),
            'outstanding_amount': Decimal("50000"),
            'disbursement_date': date(2026, 1, 1),
            'tenure_months': 10,
            'first_emi_month': 5,
            'first_emi_year': 2026,
            'status': EmployeeLoan.LoanStatus.ACTIVE
        }
    )
    if created:
        # Create one pending installment for May 2026
        LoanInstallment.objects.get_or_create(
            loan=loan,
            installment_number=1,
            due_month=5,
            due_year=2026,
            defaults={
                'emi_amount': Decimal("5000"),
                'status': LoanInstallment.InstallmentStatus.PENDING
            }
        )
        print(f"Created Sample Loan for {emp}")

    # 6. Create a Payroll Run for May 2026
    run, created = PayrollRun.objects.get_or_create(
        month=5,
        year=2026,
        defaults={'status': PayrollRun.Status.DRAFT}
    )
    if created: print(f"Created Payroll Run for May 2026")

    print("\nSetup Complete! Refresh your dashboard and click 'Run' on the May 2026 batch.")

if __name__ == "__main__":
    seed()
