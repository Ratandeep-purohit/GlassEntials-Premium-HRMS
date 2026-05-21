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
            
            # Notify admins
            from accounts.models import CustomUser
            from home.models import Notification
            staff_users = CustomUser.objects.filter(organization=request.user.organization, is_staff=True)
            for staff in staff_users:
                Notification.objects.create(
                    user=staff,
                    organization=request.user.organization,
                    title=f"New Loan Request: {employee.first_name}",
                    message=f"Requested loan of amount {principal_amount}.",
                    notification_type='LOAN',
                    link='/payroll/admin-loans/'
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
                    
            # Notify employee
            from accounts.models import CustomUser
            from home.models import Notification
            target_user = CustomUser.objects.filter(email=loan.employee.email, organization=organization).first()
            if target_user:
                Notification.objects.create(
                    user=target_user,
                    organization=organization,
                    title="Loan Request Approved",
                    message=f"Your loan request for {loan.principal_amount} has been approved.",
                    notification_type='LOAN',
                    link='/payroll/my-loans/'
                )
                    
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
            
            # Notify employee
            from accounts.models import CustomUser
            from home.models import Notification
            target_user = CustomUser.objects.filter(email=loan.employee.email, organization=organization).first()
            if target_user:
                Notification.objects.create(
                    user=target_user,
                    organization=organization,
                    title="Loan Request Rejected",
                    message=f"Your loan request for {loan.principal_amount} has been rejected.",
                    notification_type='LOAN',
                    link='/payroll/my-loans/'
                )
                
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

# ===========================================================================
# 10. ENTERPRISE INCOME TAX & INVESTMENT DECLARATIONS VIEWS
# ===========================================================================

@login_required
def my_tax_declarations(request):
    """Employee portal for Enterprise Tax & Investment declarations."""
    from .models import (
        FinancialYear, TaxRegime, TaxSlab, TaxDeclarationCategory,
        EmployeeTaxProfile, EmployeeTaxDeclaration, DeclarationProof,
        DeclarationWorkflowLog, TaxCalculationSnapshot, DeclarationCutoffPolicy
    )
    from .engine.tax_calculator import TaxCalculatorEngine
    import re

    organization = request.user.organization
    employee = Employee.objects.filter(email=request.user.email, organization=organization).first()
    
    if not employee:
        messages.error(request, "Employee profile not found.")
        return redirect('payroll')
        
    # Get or create current active Financial Year
    fy = FinancialYear.objects.filter(is_active=True).first()
    if not fy:
        fy, _ = FinancialYear.objects.get_or_create(
            name="2024-2025",
            defaults={
                "start_date": datetime.date(2024, 4, 1),
                "end_date": datetime.date(2025, 3, 31),
                "is_active": True
            }
        )
        
    # Get or create EmployeeTaxProfile
    profile, created = EmployeeTaxProfile.objects.get_or_create(
        employee=employee,
        financial_year=fy,
        defaults={
            "selected_regime": TaxRegime.objects.filter(financial_year=fy, regime_type=TaxRegime.RegimeType.NEW).first()
        }
    )
    
    # Sync profile with salary structure if CTC is not set or fresh
    salary_structure = employee.salary_structures.filter(is_active=True).first()
    if salary_structure and (profile.annual_ctc == Decimal("0.00") or created):
        profile.annual_ctc = salary_structure.ctc
        profile.basic_salary = salary_structure.basic_salary * Decimal("12.00")
        
        # HRA Exemption HRA component value
        hra_item = salary_structure.items.filter(component__code="HRA").first()
        if hra_item:
            if hra_item.component.calculation_type == SalaryComponent.CalculationType.FIXED:
                profile.hra = hra_item.fixed_amount * Decimal("12.00")
            elif hra_item.component.calculation_type == SalaryComponent.CalculationType.PERCENTAGE:
                profile.hra = salary_structure.basic_salary * hra_item.percentage * Decimal("12.00")
                
        # Special Allowance and others
        other_earnings = Decimal("0.00")
        for item in salary_structure.items.filter(component__component_type=SalaryComponent.ComponentType.EARNING):
            if item.component.code not in ["BASIC", "HRA"]:
                if item.component.calculation_type == SalaryComponent.CalculationType.FIXED:
                    other_earnings += item.fixed_amount
                elif item.component.calculation_type == SalaryComponent.CalculationType.PERCENTAGE:
                    other_earnings += salary_structure.basic_salary * item.percentage
        profile.special_allowance = other_earnings * Decimal("12.00")
        profile.save()

    # Pre-create EmployeeTaxDeclaration rows for active categories
    categories = TaxDeclarationCategory.objects.filter(is_active=True)
    for cat in categories:
        EmployeeTaxDeclaration.objects.get_or_create(
            tax_profile=profile,
            category=cat,
            defaults={
                "declared_amount": Decimal("0.00"),
                "approved_amount": Decimal("0.00"),
                "workflow_status": EmployeeTaxDeclaration.WorkflowStatus.DRAFT
            }
        )

    # Ensure we have the latest lock status from the DB (in case admin changed it)
    profile.refresh_from_db()
    # Determine if the declaration is locked either by regime lock or cutoff policy
    from django.utils import timezone
    current_month = timezone.now().month
    cutoff_policy = DeclarationCutoffPolicy.objects.filter(financial_year=fy, month=current_month).first()
    is_locked = profile.is_regime_locked or (cutoff_policy and timezone.now() > cutoff_policy.cutoff_date)

    # Handle POST action
    if request.method == "POST":
        if is_locked:
            messages.error(request, "The submission deadline for this month has passed. Edits are locked.")
            return redirect('my_tax_declarations')

        action_type = request.POST.get('action_type')

        if action_type == "save_draft" or action_type == "submit":
            # 1. Save Regime
            regime_type = request.POST.get('regime_type', 'NEW')
            regime = TaxRegime.objects.filter(financial_year=fy, regime_type=regime_type).first()
            if regime and profile.selected_regime != regime:
                old_regime = profile.selected_regime.regime_type if profile.selected_regime else "None"
                profile.selected_regime = regime
                profile.save()
                
                # Audit trail
                DeclarationWorkflowLog.objects.create(
                    action="Regime Selection Changed",
                    old_value=old_regime,
                    new_value=regime_type,
                    performed_by=request.user.username,
                    ip_address=request.META.get('REMOTE_ADDR')
                )

            # 2. Save Rent & landlord info
            rent_paid = Decimal(request.POST.get('rent_paid') or '0')
            landlord_pan = request.POST.get('landlord_pan', '').strip().upper() or None
            
            # Enforce validation: rent > 1,00,000 needs Landlord PAN
            if rent_paid > Decimal("100000.00") and not landlord_pan:
                messages.error(request, "Landlord PAN is mandatory for annual rent exceeding ₹1,00,000.")
                return redirect('my_tax_declarations')
                
            # Regex validation for PAN
            if landlord_pan and not re.match(r'^[A-Z]{5}[0-9]{4}[A-Z]$', landlord_pan):
                messages.error(request, "Invalid Landlord PAN format (should be like ABCDE1234F).")
                return redirect('my_tax_declarations')

            profile.rent_paid = rent_paid
            profile.landlord_pan = landlord_pan
            profile.prev_employer_income = Decimal(request.POST.get('prev_employer_income') or '0')
            profile.prev_employer_tds = Decimal(request.POST.get('prev_employer_tds') or '0')
            profile.other_income = Decimal(request.POST.get('other_income') or '0')
            profile.bonus = Decimal(request.POST.get('bonus') or '0')
            profile.variable_pay = Decimal(request.POST.get('variable_pay') or '0')
            profile.save()

            # 3. Save category declarations
            for cat in categories:
                declared_val = request.POST.get(f"declared_{cat.code}")
                if declared_val is not None:
                    amt = Decimal(declared_val or '0')
                    # Cap if limit exists
                    if cat.max_limit and amt > cat.max_limit:
                        amt = cat.max_limit
                    
                    decl = EmployeeTaxDeclaration.objects.filter(tax_profile=profile, category=cat).first()
                    if decl and decl.workflow_status in [EmployeeTaxDeclaration.WorkflowStatus.DRAFT, EmployeeTaxDeclaration.WorkflowStatus.REJECTED]:
                        old_val = decl.declared_amount
                        decl.declared_amount = amt
                        if action_type == "submit":
                            decl.workflow_status = EmployeeTaxDeclaration.WorkflowStatus.SUBMITTED
                        decl.save()
                        
                        if old_val != amt or action_type == "submit":
                            DeclarationWorkflowLog.objects.create(
                                declaration=decl,
                                action="Save Declaration" if action_type == "save_draft" else "Submit Declaration",
                                old_value=str(old_val),
                                new_value=str(amt),
                                performed_by=request.user.username,
                                ip_address=request.META.get('REMOTE_ADDR')
                            )

            if action_type == "submit":
                messages.success(request, "Tax declarations submitted for verification successfully!")
            else:
                messages.success(request, "Draft tax declarations saved successfully!")
            return redirect('my_tax_declarations')

        elif action_type == "upload_proof":
            category_code = request.POST.get('upload_category')
            proof_file = request.FILES.get('proof_file')
            claimed_amt = Decimal(request.POST.get('claimed_amount') or '0')
            
            if not proof_file:
                messages.error(request, "Please select a valid document file to upload.")
                return redirect('my_tax_declarations')
                
            # Limit file size to 5MB
            if proof_file.size > 5 * 1024 * 1024:
                messages.error(request, "File size exceeds 5MB limit.")
                return redirect('my_tax_declarations')
                
            # Validate file format
            ext = proof_file.name.split('.')[-1].lower()
            if ext not in ['pdf', 'jpg', 'jpeg', 'png']:
                messages.error(request, "Invalid file format. Only PDF, JPG, and PNG are allowed.")
                return redirect('my_tax_declarations')

            cat = TaxDeclarationCategory.objects.filter(code=category_code).first()
            decl = EmployeeTaxDeclaration.objects.filter(tax_profile=profile, category=cat).first()
            if decl:
                proof = DeclarationProof.objects.create(
                    declaration=decl,
                    file=proof_file,
                    document_type=proof_file.name,
                    amount_claimed=claimed_amt,
                    verification_status=DeclarationProof.VerificationStatus.PENDING
                )
                
                # Move declaration back to SUBMITTED if in draft or under review
                if decl.workflow_status in [EmployeeTaxDeclaration.WorkflowStatus.DRAFT, EmployeeTaxDeclaration.WorkflowStatus.UNDER_REVIEW]:
                    decl.workflow_status = EmployeeTaxDeclaration.WorkflowStatus.SUBMITTED
                    decl.save()

                # Audit log
                DeclarationWorkflowLog.objects.create(
                    declaration=decl,
                    action="Proof Uploaded",
                    old_value="",
                    new_value=f"File: {proof_file.name}, Claimed: {claimed_amt}",
                    performed_by=request.user.username,
                    ip_address=request.META.get('REMOTE_ADDR')
                )
                messages.success(request, f"Proof uploaded successfully for {cat.name}!")
            else:
                messages.error(request, "Failed to upload proof. Category declaration not found.")
            return redirect('my_tax_declarations')

    # Trigger calculation to ensure snapshot is accurate
    calc_result = {}
    if profile.selected_regime:
        calc_result = TaxCalculatorEngine.calculate_tax(profile, profile.selected_regime)
        # Update snapshot
        TaxCalculationSnapshot.objects.update_or_create(
            tax_profile=profile,
            is_active_for_payroll=True,
            defaults={
                "calculated_gross": Decimal(str(calc_result["gross_income"])),
                "total_exemptions": Decimal(str(calc_result["hra_exemption"] + calc_result["total_deductions"])),
                "taxable_income": Decimal(str(calc_result["taxable_income"])),
                "annual_tax": Decimal(str(calc_result["total_tax_liability"])),
                "monthly_tds": Decimal(str(calc_result["monthly_tds"]))
            }
        )

    # Get comparison recommendations
    old_regime = TaxRegime.objects.filter(financial_year=fy, regime_type=TaxRegime.RegimeType.OLD).first()
    new_regime = TaxRegime.objects.filter(financial_year=fy, regime_type=TaxRegime.RegimeType.NEW).first()
    
    old_calc = TaxCalculatorEngine.calculate_tax(profile, old_regime) if old_regime else None
    new_calc = TaxCalculatorEngine.calculate_tax(profile, new_regime) if new_regime else None

    # Determine recommended regime
    recommended = "NEW"
    if old_calc and new_calc:
        if old_calc["total_tax_liability"] < new_calc["total_tax_liability"]:
            recommended = "OLD"

    # Get user declarations and group proofs
    user_declarations = EmployeeTaxDeclaration.objects.filter(tax_profile=profile).select_related('category')
    proofs = DeclarationProof.objects.filter(declaration__tax_profile=profile)
    audit_logs = DeclarationWorkflowLog.objects.filter(Q(declaration__tax_profile=profile) | Q(declaration__isnull=True)).order_by('-id')[:10]

    context = {
        'profile': profile,
        'calc_result': calc_result,
        'old_calc': old_calc,
        'new_calc': new_calc,
        'recommended_regime': recommended,
        'declarations': user_declarations,
        'proofs': proofs,
        'audit_logs': audit_logs,
        'is_locked': is_locked,
        'cutoff_policy': cutoff_policy
    }
    return render(request, 'tax_declarations.html', context)


@login_required
def api_tax_preview(request):
    """AJAX endpoint for live tax simulation/preview on input changes."""
    from .models import EmployeeTaxProfile, TaxRegime, FinancialYear
    from .engine.tax_calculator import TaxCalculatorEngine
    
    organization = request.user.organization
    employee = Employee.objects.filter(email=request.user.email, organization=organization).first()
    if not employee:
        return JsonResponse({"error": "Employee not found"}, status=404)
        
    fy = FinancialYear.objects.filter(is_active=True).first()
    profile = EmployeeTaxProfile.objects.filter(employee=employee, financial_year=fy).first()
    if not profile:
        return JsonResponse({"error": "Tax profile not found"}, status=404)

    # Read simulated values from request parameters
    sim_regime_type = request.GET.get('regime_type', profile.selected_regime.regime_type if profile.selected_regime else 'NEW')
    
    # Create temporary simulation profile (without saving to database!)
    sim_profile = EmployeeTaxProfile(
        employee=employee,
        financial_year=fy,
        city_type=request.GET.get('city_type', profile.city_type),
        rent_paid=Decimal(request.GET.get('rent_paid') or '0'),
        prev_employer_income=Decimal(request.GET.get('prev_employer_income') or '0'),
        prev_employer_tds=Decimal(request.GET.get('prev_employer_tds') or '0'),
        other_income=Decimal(request.GET.get('other_income') or '0'),
        bonus=Decimal(request.GET.get('bonus') or '0'),
        variable_pay=Decimal(request.GET.get('variable_pay') or '0'),
        annual_ctc=profile.annual_ctc,
        basic_salary=profile.basic_salary,
        hra=profile.hra,
        special_allowance=profile.special_allowance
    )
    
    regime = TaxRegime.objects.filter(financial_year=fy, regime_type=sim_regime_type).first()
    if not regime:
        return JsonResponse({"error": "Regime not found"}, status=400)
        
    # We must also mock dynamic declarations that the user is editing in the DOM!
    # Let's override the database query inside calculator by passing manual structures or pre-saving/fetching them
    # Actually, we can run calculations for BOTH regimes and send JSON back
    old_regime = TaxRegime.objects.filter(financial_year=fy, regime_type=TaxRegime.RegimeType.OLD).first()
    new_regime = TaxRegime.objects.filter(financial_year=fy, regime_type=TaxRegime.RegimeType.NEW).first()
    
    # Fetch user inputs from request parameters for active categories
    from .models import EmployeeTaxDeclaration, TaxDeclarationCategory
    sim_declarations = []
    for cat in TaxDeclarationCategory.objects.filter(is_active=True):
        val = Decimal(request.GET.get(f'declared_{cat.code}') or '0')
        sim_declarations.append(EmployeeTaxDeclaration(category=cat, declared_amount=val, approved_amount=val))
        
    with transaction.atomic():
        # Update actual profile fields temporarily
        profile.city_type = sim_profile.city_type
        profile.rent_paid = sim_profile.rent_paid
        profile.prev_employer_income = sim_profile.prev_employer_income
        profile.prev_employer_tds = sim_profile.prev_employer_tds
        profile.other_income = sim_profile.other_income
        profile.bonus = sim_profile.bonus
        profile.variable_pay = sim_profile.variable_pay
        profile.save()
        
        for decl in sim_declarations:
            db_decl = EmployeeTaxDeclaration.objects.filter(tax_profile=profile, category=decl.category).first()
            if db_decl:
                db_decl.declared_amount = decl.declared_amount
                db_decl.save()
                
        old_calc = TaxCalculatorEngine.calculate_tax(profile, old_regime) if old_regime else None
        new_calc = TaxCalculatorEngine.calculate_tax(profile, new_regime) if new_regime else None
        
        # Rollback all changes
        transaction.set_rollback(True)

    recommended = "NEW"
    if old_calc and new_calc:
        if old_calc["total_tax_liability"] < new_calc["total_tax_liability"]:
            recommended = "OLD"

    return JsonResponse({
        "old_regime": old_calc,
        "new_regime": new_calc,
        "recommended_regime": recommended
    })


@login_required
def admin_tax_review(request):
    """HR & Finance Panel for Reviewing and Verifying Employee Tax Declarations & Proofs."""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_tax_declarations')

    from .models import EmployeeTaxProfile, DeclarationProof
    organization = request.user.organization
    
    profiles = EmployeeTaxProfile.objects.filter(
        Q(employee__organization=organization) | Q(employee__organization__isnull=True)
    ).select_related('employee', 'financial_year', 'selected_regime')
    
    # Filter pending proofs queue
    pending_proofs = DeclarationProof.objects.filter(
        verification_status=DeclarationProof.VerificationStatus.PENDING,
        declaration__tax_profile__employee__organization=organization
    ).select_related('declaration__tax_profile__employee', 'declaration__category')

    context = {
        'profiles': profiles,
        'pending_proofs': pending_proofs
    }
    return render(request, 'admin_tax_review.html', context)


@login_required
def admin_verify_proof(request, proof_id):
    """HR/Finance decision view to approve or reject dynamic proofs."""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_tax_declarations')

    from .models import DeclarationProof, EmployeeTaxDeclaration, DeclarationWorkflowLog, TaxCalculationSnapshot
    from .engine.tax_calculator import TaxCalculatorEngine
    
    proof = get_object_or_404(DeclarationProof, pk=proof_id)
    decl = proof.declaration
    profile = decl.tax_profile

    if request.method == "POST":
        status = request.POST.get('status')  # 'VERIFIED' or 'REJECTED'
        remarks = request.POST.get('remarks', '').strip()
        approved_amt = Decimal(request.POST.get('approved_amount') or '0')

        if status not in ['VERIFIED', 'REJECTED']:
            messages.error(request, "Invalid verification action.")
            return redirect('admin_tax_review')

        old_status = proof.verification_status
        proof.verification_status = status
        proof.reviewer_remarks = remarks
        if status == 'VERIFIED':
            proof.amount_claimed = approved_amt
        proof.save()

        # Update parent declaration's approved amount
        all_proofs = decl.proofs.all()
        total_approved = Decimal("0.00")
        has_pending = False
        
        for p in all_proofs:
            if p.verification_status == 'VERIFIED':
                total_approved += p.amount_claimed
            elif p.verification_status == 'PENDING':
                has_pending = True

        decl.approved_amount = total_approved
        
        if has_pending:
            decl.workflow_status = EmployeeTaxDeclaration.WorkflowStatus.UNDER_REVIEW
        else:
            decl.workflow_status = EmployeeTaxDeclaration.WorkflowStatus.APPROVED if total_approved > 0 else EmployeeTaxDeclaration.WorkflowStatus.REJECTED
        decl.save()

        # Recalculate and update snapshot
        calc_result = TaxCalculatorEngine.calculate_tax(profile, profile.selected_regime, use_approved=True)
        TaxCalculationSnapshot.objects.update_or_create(
            tax_profile=profile,
            is_active_for_payroll=True,
            defaults={
                "calculated_gross": Decimal(str(calc_result["gross_income"])),
                "total_exemptions": Decimal(str(calc_result["hra_exemption"] + calc_result["total_deductions"])),
                "taxable_income": Decimal(str(calc_result["taxable_income"])),
                "annual_tax": Decimal(str(calc_result["total_tax_liability"])),
                "monthly_tds": Decimal(str(calc_result["monthly_tds"]))
            }
        )

        # Audit trail
        DeclarationWorkflowLog.objects.create(
            declaration=decl,
            action=f"Proof {status}",
            old_value=old_status,
            new_value=f"Status: {status}, Approved Amt: {approved_amt}",
            performed_by=request.user.username,
            ip_address=request.META.get('REMOTE_ADDR')
        )

        messages.success(request, f"Proof document has been successfully verified as {status}!")
        return redirect('admin_tax_review')

    context = {
        'proof': proof,
        'decl': decl,
        'profile': profile
    }
    return render(request, 'admin_verify_proof.html', context)


@login_required
def admin_lock_profile(request, profile_id):
    """HR/Finance override view to lock or unlock an employee's tax profile."""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_tax_declarations')

    from .models import EmployeeTaxProfile, DeclarationWorkflowLog
    profile = get_object_or_404(EmployeeTaxProfile, pk=profile_id)
    
    old_state = profile.is_regime_locked
    profile.is_regime_locked = not old_state
    profile.save()

    action = "Locked" if profile.is_regime_locked else "Unlocked"
    
    # Audit log
    DeclarationWorkflowLog.objects.create(
        action=f"Profile {action} By Admin",
        old_value=str(old_state),
        new_value=str(profile.is_regime_locked),
        performed_by=request.user.username,
        ip_address=request.META.get('REMOTE_ADDR')
    )

    messages.success(request, f"Employee's tax profile has been {action.lower()} successfully!")
    return redirect('admin_tax_review')


@login_required
def admin_tax_audit_log(request, profile_id):
    """View complete history log for an employee's profile."""
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('my_tax_declarations')

    from .models import EmployeeTaxProfile, DeclarationWorkflowLog
    profile = get_object_or_404(EmployeeTaxProfile, pk=profile_id)
    logs = DeclarationWorkflowLog.objects.filter(
        Q(declaration__tax_profile=profile) | Q(declaration__isnull=True)
    ).order_by('-id')

    context = {
        'profile': profile,
        'logs': logs
    }
    return render(request, 'admin_tax_audit_log.html', context)
