import datetime
from datetime import date
from decimal import Decimal
import random

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, Q
from django.utils import timezone
from django.core.exceptions import ValidationError

from employees.models import Employee, Department
from .models import (
    SalaryComponent, SalaryStructure, SalaryStructureItem, 
    PayrollRun, EmployeePayslip, PayslipItem, EmployeeLoan, 
    LoanInstallment, Arrear
)
from payroll.engine.processor import PayrollProcessor

@login_required
def payroll_dashboard(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_payslips')
        
    organization = request.user.organization
    runs = PayrollRun.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True)
    ).order_by('-year', '-month')
    departments = Department.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True)
    )
    context = {
        'runs': runs,
        'departments': departments,
    }
    return render(request, 'payroll.html', context)

@login_required
def salary_list(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_payslips')
        
    organization = request.user.organization
    employees = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        is_active=True,
        is_deleted=False
    )
    for emp in employees:
        emp.current_structure = SalaryStructure.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            employee=emp,
            is_active=True
        ).order_by('-effective_date').first()
    return render(request, 'salary_list.html', {'employees': employees})

@login_required
def create_payroll_run(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_payslips')
        
    if request.method == 'POST':
        organization = request.user.organization
        month = int(request.POST.get('month'))
        year = int(request.POST.get('year'))
        dept_id = request.POST.get('department')
        
        department = None
        if dept_id:
            try:
                department = Department.objects.get(
                    Q(organization=organization) | Q(organization__isnull=True),
                    id=dept_id
                )
            except Department.DoesNotExist:
                messages.error(request, "Invalid department selected.")
                return redirect('payroll')
        
        # Check if already exists
        if PayrollRun.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            month=month,
            year=year,
            department=department
        ).exists():
            messages.error(request, "A payroll run for this period and department already exists.")
            return redirect('payroll')
            
        try:
            run = PayrollRun.objects.create(
                organization=organization,
                month=month,
                year=year,
                department=department,
                status=PayrollRun.Status.DRAFT
            )
            messages.success(request, f"Successfully initialized payroll run for {run.get_month_display()} {year}.")
        except Exception as e:
            messages.error(request, f"Error initializing payroll run: {e}")
            
    return redirect('payroll')

@login_required
def run_payroll(request, run_id):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_payslips')
        
    organization = request.user.organization
    try:
        run = PayrollRun.objects.get(
            Q(organization=organization) | Q(organization__isnull=True),
            id=run_id
        )
    except PayrollRun.DoesNotExist:
        messages.error(request, "Payroll run not found.")
        return redirect('payroll')
        
    if run.is_locked:
        messages.error(request, "Cannot run payroll on a locked/finalized batch.")
        return redirect('payroll')
        
    try:
        processor = PayrollProcessor(run.id)
        count = processor.process()
        messages.success(request, f"Successfully processed payroll for {count} employees.")
    except Exception as e:
        messages.error(request, f"Error processing payroll: {e}")
        
    return redirect('payroll')

@login_required
def payslip_list(request, run_id):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_payslips')
        
    organization = request.user.organization
    try:
        payroll_run = PayrollRun.objects.get(
            Q(organization=organization) | Q(organization__isnull=True),
            id=run_id
        )
    except PayrollRun.DoesNotExist:
        messages.error(request, "Payroll run not found.")
        return redirect('payroll')
        
    payslips = EmployeePayslip.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        payroll_run=payroll_run
    )
    context = {
        'payroll_run': payroll_run,
        'payslips': payslips,
    }
    return render(request, 'payslip_list.html', context)

@login_required
def payslip_detail(request, payslip_id):
    organization = request.user.organization
    try:
        payslip = EmployeePayslip.objects.get(
            Q(organization=organization) | Q(organization__isnull=True),
            id=payslip_id
        )
    except EmployeePayslip.DoesNotExist:
        messages.error(request, "Payslip not found.")
        if not (request.user.is_staff or request.user.is_superuser):
            return redirect('my_payslips')
        return redirect('payroll')
        
    is_staff = request.user.is_staff or request.user.is_superuser
    if not is_staff and payslip.employee.email != request.user.email:
        messages.error(request, "Access denied.")
        return redirect('my_payslips')
        
    earnings = payslip.items.filter(item_type=PayslipItem.ItemType.EARNING)
    deductions = payslip.items.filter(item_type=PayslipItem.ItemType.DEDUCTION)
    
    context = {
        'payslip': payslip,
        'earnings': earnings,
        'deductions': deductions,
        'now': timezone.now(),
    }
    return render(request, 'payslip_detail.html', context)

@login_required
def manage_employee_salary(request, employee_id):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_payslips')
        
    organization = request.user.organization
    try:
        employee = Employee.objects.get(
            Q(organization=organization) | Q(organization__isnull=True),
            id=employee_id
        )
    except Employee.DoesNotExist:
        messages.error(request, "Employee not found.")
        return redirect('salary_list')
        
    if request.method == 'POST':
        ctc = Decimal(request.POST.get('ctc', '0'))
        gross_salary = Decimal(request.POST.get('gross_salary', '0'))
        basic_salary = Decimal(request.POST.get('basic_salary', '0'))
        effective_date_str = request.POST.get('effective_date')
        
        selected_component_ids = request.POST.getlist('components')
        
        try:
            with transaction.atomic():
                # 1. Create the new SalaryStructure
                structure = SalaryStructure(
                    employee=employee,
                    organization=organization,
                    ctc=ctc,
                    gross_salary=gross_salary,
                    basic_salary=basic_salary,
                    effective_date=effective_date_str
                )
                structure.clean()
                structure.save()
                
                # 2. Add selected components
                for comp_id in selected_component_ids:
                    component = SalaryComponent.objects.get(id=comp_id)
                    item = SalaryStructureItem(
                        salary_structure=structure,
                        component=component,
                        organization=organization
                    )
                    
                    if component.calculation_type == SalaryComponent.CalculationType.FIXED:
                        fixed_val = request.POST.get(f'fixed_{comp_id}', '0')
                        item.fixed_amount = Decimal(fixed_val)
                    elif component.calculation_type == SalaryComponent.CalculationType.PERCENTAGE:
                        perc_val = request.POST.get(f'perc_{comp_id}', '0')
                        item.percentage = Decimal(perc_val) / Decimal('100')
                    
                    item.clean()
                    item.save()
                    
            messages.success(request, f"Successfully updated salary structure for {employee.first_name} {employee.last_name}.")
            return redirect('salary_list')
        except ValidationError as e:
            err_msg = ""
            if hasattr(e, 'message_dict'):
                err_msg = "; ".join([f"{k}: {', '.join(v)}" for k, v in e.message_dict.items()])
            else:
                err_msg = ", ".join(e.messages)
            messages.error(request, f"Validation Error: {err_msg}")
        except Exception as e:
            messages.error(request, f"Error saving salary structure: {e}")
            
    structure = SalaryStructure.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        employee=employee,
        is_active=True
    ).order_by('-effective_date').first()
    components = SalaryComponent.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        is_active=True
    )
    
    context = {
        'employee': employee,
        'structure': structure,
        'components': components,
    }
    return render(request, 'manage_salary.html', context)

@login_required
def salary_components_list(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_payslips')
        
    organization = request.user.organization
    if request.method == 'POST':
        name = request.POST.get('name')
        code = request.POST.get('code').upper()
        component_type = request.POST.get('component_type')
        calculation_type = request.POST.get('calculation_type')
        formula = request.POST.get('formula', '')
        is_taxable = 'is_taxable' in request.POST
        
        try:
            component = SalaryComponent(
                organization=organization,
                name=name,
                code=code,
                component_type=component_type,
                calculation_type=calculation_type,
                formula=formula,
                is_taxable=is_taxable
            )
            component.clean()
            component.save()
            messages.success(request, f"Successfully created component '{name}'.")
        except ValidationError as e:
            err_msg = ", ".join(e.messages) if hasattr(e, 'messages') else str(e)
            messages.error(request, f"Validation error: {err_msg}")
        except Exception as e:
            messages.error(request, f"Error creating component: {e}")
            
        return redirect('salary_components')
        
    components = SalaryComponent.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True)
    )
    context = {
        'components': components,
    }
    return render(request, 'salary_components.html', context)

@login_required
def my_payslips(request):
    organization = request.user.organization
    employee = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        email=request.user.email,
        is_active=True,
        is_deleted=False
    ).first()
    
    payslips = []
    if employee:
        payslips = EmployeePayslip.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            employee=employee
        ).order_by('-payroll_run__year', '-payroll_run__month')
        
    context = {
        'employee': employee,
        'payslips': payslips,
    }
    return render(request, 'my_payslips.html', context)

@login_required
def my_salary_structure(request):
    organization = request.user.organization
    employee = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        email=request.user.email,
        is_active=True,
        is_deleted=False
    ).first()
    
    structure = None
    earnings_items = []
    deduction_items = []
    
    if employee:
        structure = SalaryStructure.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            employee=employee,
            is_active=True
        ).order_by('-effective_date').first()
        if structure:
            earnings_items = structure.items.filter(component__component_type=SalaryComponent.ComponentType.EARNING)
            deduction_items = structure.items.filter(component__component_type=SalaryComponent.ComponentType.DEDUCTION)
            
    context = {
        'employee': employee,
        'structure': structure,
        'earnings_items': earnings_items,
        'deduction_items': deduction_items,
    }
    return render(request, 'my_salary_structure.html', context)

@login_required
def my_loans(request):
    organization = request.user.organization
    employee = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        email=request.user.email,
        is_active=True,
        is_deleted=False
    ).first()
    
    loans = []
    if employee:
        loans = EmployeeLoan.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            employee=employee
        ).order_by('-disbursement_date')
        
    context = {
        'employee': employee,
        'loans': loans,
        'loan_types': EmployeeLoan.LoanType.choices,
    }
    return render(request, 'my_loans.html', context)

@login_required
def request_loan(request):
    organization = request.user.organization
    employee = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        email=request.user.email,
        is_active=True,
        is_deleted=False
    ).first()
    
    if not employee:
        messages.error(request, "Employee record not found.")
        return redirect('my_loans')
        
    if request.method == 'POST':
        loan_type = request.POST.get('loan_type')
        principal_amount = Decimal(request.POST.get('principal_amount', '0'))
        tenure_months = int(request.POST.get('tenure_months', '1'))
        reason = request.POST.get('reason', '')
        
        # Calculate EMI
        emi_amount = (principal_amount / Decimal(str(tenure_months))).quantize(Decimal('0.01'))
        
        today = date.today()
        if today.month == 12:
            first_emi_month = 1
            first_emi_year = today.year + 1
        else:
            first_emi_month = today.month + 1
            first_emi_year = today.year
            
        # Generate a unique loan number
        random_suffix = random.randint(1000, 9999)
        loan_number = f"LN-{today.year}{today.month:02d}-{random_suffix}"
        while EmployeeLoan.objects.filter(loan_number=loan_number).exists():
            random_suffix = random.randint(1000, 9999)
            loan_number = f"LN-{today.year}{today.month:02d}-{random_suffix}"
            
        try:
            loan = EmployeeLoan.objects.create(
                organization=organization,
                employee=employee,
                loan_type=loan_type,
                loan_number=loan_number,
                principal_amount=principal_amount,
                emi_amount=emi_amount,
                outstanding_amount=principal_amount,
                disbursement_date=today,
                tenure_months=tenure_months,
                first_emi_month=first_emi_month,
                first_emi_year=first_emi_year,
                status=EmployeeLoan.LoanStatus.PENDING_APPROVAL,
                approval_notes=reason
            )
            messages.success(request, "Loan request submitted successfully and is pending approval.")
        except Exception as e:
            messages.error(request, f"Error requesting loan: {e}")
            
    return redirect('my_loans')

@login_required
def admin_loans(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_loans')
        
    organization = request.user.organization
    current_status = request.GET.get('status')
    
    loans = EmployeeLoan.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True)
    )
    if current_status:
        loans = loans.filter(status=current_status)
        
    loans = loans.order_by('-disbursement_date')
    
    # Calculate stats
    active_approved_loans = EmployeeLoan.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        status__in=[EmployeeLoan.LoanStatus.ACTIVE, EmployeeLoan.LoanStatus.APPROVED, EmployeeLoan.LoanStatus.CLOSED]
    )
    total_disbursed = active_approved_loans.aggregate(Sum('principal_amount'))['principal_amount__sum'] or Decimal('0.00')
    total_outstanding = EmployeeLoan.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True)
    ).aggregate(Sum('outstanding_amount'))['outstanding_amount__sum'] or Decimal('0.00')
    pending_count = EmployeeLoan.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        status=EmployeeLoan.LoanStatus.PENDING_APPROVAL
    ).count()
    
    employees = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        is_active=True,
        is_deleted=False
    )
    
    context = {
        'loans': loans,
        'total_disbursed': total_disbursed,
        'total_outstanding': total_outstanding,
        'pending_count': pending_count,
        'status_choices': EmployeeLoan.LoanStatus.choices,
        'current_status': current_status,
        'employees': employees,
        'loan_types': EmployeeLoan.LoanType.choices,
    }
    return render(request, 'admin_loans.html', context)

@login_required
def admin_approve_loan(request, loan_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_loans')
        
    organization = request.user.organization
    try:
        loan = EmployeeLoan.objects.get(
            Q(organization=organization) | Q(organization__isnull=True),
            id=loan_id
        )
    except EmployeeLoan.DoesNotExist:
        messages.error(request, "Loan not found.")
        return redirect('admin_loans')
        
    if loan.status != EmployeeLoan.LoanStatus.PENDING_APPROVAL:
        messages.error(request, "Only pending loans can be approved.")
        return redirect('admin_loans')
        
    try:
        with transaction.atomic():
            loan.status = EmployeeLoan.LoanStatus.ACTIVE
            loan.save()
            
            month = loan.first_emi_month
            year = loan.first_emi_year
            remaining_balance = loan.principal_amount
            
            for i in range(1, loan.tenure_months + 1):
                if i == loan.tenure_months:
                    emi = remaining_balance
                    balance_after = Decimal('0.00')
                else:
                    emi = loan.emi_amount
                    balance_after = remaining_balance - emi
                    
                LoanInstallment.objects.create(
                    loan=loan,
                    organization=organization,
                    installment_number=i,
                    due_month=month,
                    due_year=year,
                    emi_amount=emi,
                    principal_component=emi,
                    interest_component=Decimal('0.00'),
                    balance_after_emi=balance_after,
                    status=LoanInstallment.InstallmentStatus.PENDING
                )
                remaining_balance = balance_after
                
                month += 1
                if month > 12:
                    month = 1
                    year += 1
                    
        messages.success(request, f"Loan {loan.loan_number} has been approved and active repayment schedule generated.")
    except Exception as e:
        messages.error(request, f"Error approving loan: {e}")
        
    return redirect('admin_loans')

@login_required
def admin_reject_loan(request, loan_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_loans')
        
    organization = request.user.organization
    try:
        loan = EmployeeLoan.objects.get(
            Q(organization=organization) | Q(organization__isnull=True),
            id=loan_id
        )
    except EmployeeLoan.DoesNotExist:
        messages.error(request, "Loan not found.")
        return redirect('admin_loans')
        
    if loan.status != EmployeeLoan.LoanStatus.PENDING_APPROVAL:
        messages.error(request, "Only pending loans can be rejected.")
        return redirect('admin_loans')
        
    if request.method == 'POST':
        rejection_reason = request.POST.get('rejection_reason', '')
        try:
            loan.status = EmployeeLoan.LoanStatus.REJECTED
            loan.approval_notes = rejection_reason
            loan.save()
            messages.success(request, f"Loan {loan.loan_number} has been rejected.")
        except Exception as e:
            messages.error(request, f"Error rejecting loan: {e}")
            
    return redirect('admin_loans')

@login_required
def admin_create_loan(request):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_loans')
        
    organization = request.user.organization
    
    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        loan_type = request.POST.get('loan_type')
        principal_amount = Decimal(request.POST.get('principal_amount', '0'))
        tenure_months = int(request.POST.get('tenure_months', '1'))
        notes = request.POST.get('notes', '')
        
        try:
            employee = Employee.objects.get(
                Q(organization=organization) | Q(organization__isnull=True),
                id=employee_id
            )
        except Employee.DoesNotExist:
            messages.error(request, "Selected employee not found.")
            return redirect('admin_loans')
            
        emi_amount = (principal_amount / Decimal(str(tenure_months))).quantize(Decimal('0.01'))
        
        today = date.today()
        if today.month == 12:
            first_emi_month = 1
            first_emi_year = today.year + 1
        else:
            first_emi_month = today.month + 1
            first_emi_year = today.year
            
        random_suffix = random.randint(1000, 9999)
        loan_number = f"LN-{today.year}{today.month:02d}-{random_suffix}"
        while EmployeeLoan.objects.filter(loan_number=loan_number).exists():
            random_suffix = random.randint(1000, 9999)
            loan_number = f"LN-{today.year}{today.month:02d}-{random_suffix}"
            
        try:
            with transaction.atomic():
                loan = EmployeeLoan.objects.create(
                    organization=organization,
                    employee=employee,
                    loan_type=loan_type,
                    loan_number=loan_number,
                    principal_amount=principal_amount,
                    emi_amount=emi_amount,
                    outstanding_amount=principal_amount,
                    disbursement_date=today,
                    tenure_months=tenure_months,
                    first_emi_month=first_emi_month,
                    first_emi_year=first_emi_year,
                    status=EmployeeLoan.LoanStatus.ACTIVE,
                    approval_notes=notes
                )
                
                month = first_emi_month
                year = first_emi_year
                remaining_balance = principal_amount
                
                for i in range(1, tenure_months + 1):
                    if i == tenure_months:
                        emi = remaining_balance
                        balance_after = Decimal('0.00')
                    else:
                        emi = emi_amount
                        balance_after = remaining_balance - emi
                        
                    LoanInstallment.objects.create(
                        loan=loan,
                        organization=organization,
                        installment_number=i,
                        due_month=month,
                        due_year=year,
                        emi_amount=emi,
                        principal_component=emi,
                        interest_component=Decimal('0.00'),
                        balance_after_emi=balance_after,
                        status=LoanInstallment.InstallmentStatus.PENDING
                    )
                    remaining_balance = balance_after
                    
                    month += 1
                    if month > 12:
                        month = 1
                        year += 1
                        
            messages.success(request, f"Successfully disbursed loan {loan.loan_number} for {employee.first_name} {employee.last_name}.")
        except Exception as e:
            messages.error(request, f"Error creating loan: {e}")
            
    return redirect('admin_loans')

@login_required
def admin_arrears(request):
    if not (request.user.is_staff or request.user.is_superuser):
        return redirect('my_arrears')
        
    organization = request.user.organization
    
    if request.method == 'POST':
        employee_id = request.POST.get('employee')
        component_id = request.POST.get('component')
        arrear_type = request.POST.get('arrear_type')
        from_month = int(request.POST.get('from_month', '1'))
        from_year = int(request.POST.get('from_year', '2026'))
        to_month = int(request.POST.get('to_month', '1'))
        to_year = int(request.POST.get('to_year', '2026'))
        amount = Decimal(request.POST.get('amount', '0'))
        reason = request.POST.get('reason', '')
        
        try:
            employee = Employee.objects.get(
                Q(organization=organization) | Q(organization__isnull=True),
                id=employee_id
            )
            component = SalaryComponent.objects.get(
                Q(organization=organization) | Q(organization__isnull=True),
                id=component_id
            )
            
            with transaction.atomic():
                arrear = Arrear(
                    organization=organization,
                    employee=employee,
                    component=component,
                    arrear_type=arrear_type,
                    from_month=from_month,
                    from_year=from_year,
                    to_month=to_month,
                    to_year=to_year,
                    amount=amount,
                    reason=reason,
                    status=Arrear.ArrearStatus.PENDING
                )
                arrear.clean()
                arrear.save()
            messages.success(request, f"Successfully created arrear/adjustment for {employee.first_name} {employee.last_name}.")
        except ValidationError as e:
            err_msg = ", ".join(e.messages) if hasattr(e, 'messages') else str(e)
            messages.error(request, f"Validation error: {err_msg}")
        except Exception as e:
            messages.error(request, f"Error creating arrear: {e}")
            
        return redirect('admin_arrears')
        
    # GET Request
    current_status = request.GET.get('status')
    current_type = request.GET.get('arrear_type')
    current_employee_id = request.GET.get('employee')
    
    arrears = Arrear.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True)
    )
    
    if current_status:
        arrears = arrears.filter(status=current_status)
    if current_type:
        arrears = arrears.filter(arrear_type=current_type)
    if current_employee_id:
        arrears = arrears.filter(employee_id=current_employee_id)
        
    arrears = arrears.order_by('-from_year', '-from_month')
    
    # Context data for filters and creation form
    employees = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        is_active=True,
        is_deleted=False
    ).order_by('first_name', 'last_name')
    
    components = SalaryComponent.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        is_active=True
    ).order_by('name')
    
    context = {
        'arrears': arrears,
        'employees': employees,
        'components': components,
        'status_choices': Arrear.ArrearStatus.choices,
        'type_choices': Arrear.ArrearType.choices,
        'month_choices': PayrollRun.Month.choices,
        'current_status': current_status,
        'current_type': current_type,
        'current_employee_id': current_employee_id,
        'current_year': timezone.now().year,
    }
    return render(request, 'admin_arrears.html', context)

@login_required
def admin_cancel_arrear(request, arrear_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_arrears')
        
    organization = request.user.organization
    try:
        arrear = Arrear.objects.get(
            Q(organization=organization) | Q(organization__isnull=True),
            id=arrear_id
        )
    except Arrear.DoesNotExist:
        messages.error(request, "Arrear record not found.")
        return redirect('admin_arrears')
        
    if arrear.status != Arrear.ArrearStatus.PENDING:
        messages.error(request, "Only pending arrears can be cancelled.")
        return redirect('admin_arrears')
        
    try:
        arrear.status = Arrear.ArrearStatus.CANCELLED
        arrear.save()
        messages.success(request, f"Arrear record has been successfully cancelled.")
    except Exception as e:
        messages.error(request, f"Error cancelling arrear: {e}")
        
    return redirect('admin_arrears')

@login_required
def my_arrears(request):
    organization = request.user.organization
    employee = Employee.objects.filter(
        Q(organization=organization) | Q(organization__isnull=True),
        email=request.user.email,
        is_active=True,
        is_deleted=False
    ).first()
    
    arrears = []
    pending_earnings = Decimal('0.00')
    pending_recoveries = Decimal('0.00')
    
    if employee:
        arrears = Arrear.objects.filter(
            Q(organization=organization) | Q(organization__isnull=True),
            employee=employee
        ).order_by('-from_year', '-from_month')
        
        for arr in arrears:
            if arr.status == Arrear.ArrearStatus.PENDING:
                if arr.arrear_type == Arrear.ArrearType.EARNING:
                    pending_earnings += arr.amount
                elif arr.arrear_type == Arrear.ArrearType.DEDUCTION:
                    pending_recoveries += arr.amount
        
    context = {
        'employee': employee,
        'arrears': arrears,
        'pending_earnings': pending_earnings,
        'pending_recoveries': pending_recoveries,
        'status_choices': Arrear.ArrearStatus.choices,
        'type_choices': Arrear.ArrearType.choices,
    }
    return render(request, 'my_arrears.html', context)
