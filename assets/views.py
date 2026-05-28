from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q
from django.urls import reverse
from django.utils import timezone
from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError
from employees.models import Employee
from .models import AssetCategory, Asset, AssetAssignment, AssetRequest

# --- Admin Views ---

@login_required
def asset_dashboard_view(request):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    organization = request.user.organization
    
    total_assets = Asset.objects.filter(organization=organization).count()
    assigned_assets = Asset.objects.filter(organization=organization, status='ASSIGNED').count()
    available_assets = Asset.objects.filter(organization=organization, status='AVAILABLE').count()
    maintenance_assets = Asset.objects.filter(organization=organization, status='MAINTENANCE').count()
    
    recent_assignments = AssetAssignment.objects.filter(organization=organization).order_by('-assigned_date')[:5]
    pending_requests = AssetRequest.objects.filter(organization=organization, status='PENDING').order_by('-created_at')[:5]
    
    categories = AssetCategory.objects.filter(organization=organization).annotate(
        total=Count('assets'),
        assigned=Count('assets', filter=Q(assets__status='ASSIGNED'))
    )

    context = {
        'total_assets': total_assets,
        'assigned_assets': assigned_assets,
        'available_assets': available_assets,
        'maintenance_assets': maintenance_assets,
        'recent_assignments': recent_assignments,
        'pending_requests': pending_requests,
        'categories': categories,
    }
    return render(request, 'assets/dashboard.html', context)

@login_required
def inventory_list_view(request):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    assets = Asset.objects.filter(organization=request.user.organization).select_related('category')
    
    search_query = request.GET.get('search', '')
    status_filter = request.GET.get('status', '')
    category_filter = request.GET.get('category', '')
    
    if search_query:
        assets = assets.filter(
            Q(name__icontains=search_query) | 
            Q(asset_code__icontains=search_query) |
            Q(serial_number__icontains=search_query)
        )
    if status_filter:
        assets = assets.filter(status=status_filter)
    if category_filter:
        assets = assets.filter(category_id=category_filter)
        
    categories = AssetCategory.objects.filter(organization=request.user.organization)
        
    context = {
        'assets': assets.order_by('-created_at'),
        'categories': categories,
        'search_query': search_query,
        'status_filter': status_filter,
        'category_filter': category_filter,
    }
    return render(request, 'assets/inventory_list.html', context)

@login_required
def add_asset_view(request):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    categories = AssetCategory.objects.filter(organization=request.user.organization)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        asset_code = request.POST.get('asset_code', '').strip()
        category_id = request.POST.get('category_id')
        serial_number = request.POST.get('serial_number', '').strip()
        brand = request.POST.get('brand', '').strip()
        model_number = request.POST.get('model_number', '').strip()
        condition = request.POST.get('condition', 'GOOD')
        location = request.POST.get('location', '').strip()
        
        # Prepare repopulated asset data dictionary for re-rendering on error
        form_asset = {
            'name': name,
            'asset_code': asset_code,
            'category': {'id': int(category_id) if category_id else None},
            'serial_number': serial_number,
            'brand': brand,
            'model_number': model_number,
            'condition': condition,
            'location': location,
        }
        
        if not asset_code or not name or not category_id:
            messages.error(request, "Please fill in all required fields.")
            return render(request, 'assets/asset_form.html', {
                'categories': categories,
                'asset': form_asset
            })
            
        # Check globally for duplicate asset_code (active and soft-deleted)
        existing_asset = Asset.all_objects.filter(
            organization=request.user.organization,
            asset_code__iexact=asset_code
        ).first()
        if existing_asset:
            if not existing_asset.is_deleted:
                messages.error(request, f"An active asset with code '{asset_code}' already exists.")
            else:
                messages.error(request, f"A soft-deleted asset with code '{asset_code}' already exists. Please choose a different code.")
            return render(request, 'assets/asset_form.html', {
                'categories': categories,
                'asset': form_asset
            })
            
        try:
            category = get_object_or_404(AssetCategory, id=category_id, organization=request.user.organization)
            Asset.objects.create(
                organization=request.user.organization,
                name=name,
                asset_code=asset_code,
                category=category,
                serial_number=serial_number,
                brand=brand,
                model_number=model_number,
                condition=condition,
                location=location,
                created_by=request.user
            )
            messages.success(request, f"Asset {asset_code} created successfully.")
            return redirect('assets:inventory')
        except IntegrityError:
            messages.error(request, "A database conflict occurred. The asset code might already exist.")
        except Exception as e:
            messages.error(request, f"An unexpected error occurred: {e}")
            
        return render(request, 'assets/asset_form.html', {
            'categories': categories,
            'asset': form_asset
        })
        
    return render(request, 'assets/asset_form.html', {'categories': categories})

@login_required
def edit_asset_view(request, asset_id):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    asset = get_object_or_404(Asset, id=asset_id, organization=request.user.organization)
    categories = AssetCategory.objects.filter(organization=request.user.organization)
    
    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        category_id = request.POST.get('category_id')
        serial_number = request.POST.get('serial_number', '').strip()
        brand = request.POST.get('brand', '').strip()
        model_number = request.POST.get('model_number', '').strip()
        condition = request.POST.get('condition', 'GOOD')
        status = request.POST.get('status', 'AVAILABLE')
        location = request.POST.get('location', '').strip()
        
        # In case of validation error, temporarily set these properties on the asset object
        # so they repopulate the form, but do not call .save() yet
        asset.name = name
        asset.serial_number = serial_number
        asset.brand = brand
        asset.model_number = model_number
        asset.condition = condition
        asset.status = status
        asset.location = location
        
        if category_id:
            try:
                asset.category = AssetCategory.objects.get(id=category_id, organization=request.user.organization)
            except AssetCategory.DoesNotExist:
                messages.error(request, "Selected category not found.")
                return render(request, 'assets/asset_form.html', {'asset': asset, 'categories': categories})
                
        if not name or not category_id:
            messages.error(request, "Please fill in all required fields.")
            return render(request, 'assets/asset_form.html', {'asset': asset, 'categories': categories})
            
        try:
            asset.updated_by = request.user
            asset.save()
            messages.success(request, "Asset updated successfully.")
            return redirect('assets:inventory')
        except IntegrityError:
            messages.error(request, "A database conflict occurred while saving changes.")
        except Exception as e:
            messages.error(request, f"An unexpected error occurred: {e}")
            
    return render(request, 'assets/asset_form.html', {'asset': asset, 'categories': categories})

@login_required
def assign_asset_view(request, asset_id):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    asset = get_object_or_404(Asset, id=asset_id, organization=request.user.organization)
    employees = Employee.objects.filter(organization=request.user.organization, is_active=True, is_deleted=False)
    
    if asset.status != 'AVAILABLE':
        messages.error(request, "Only available assets can be assigned.")
        return redirect('assets:inventory')
        
    if request.method == 'POST':
        employee_id = request.POST.get('employee_id')
        condition_at_issue = request.POST.get('condition_at_issue', 'GOOD')
        expected_return_date = request.POST.get('expected_return_date') or None
        
        if not employee_id:
            messages.error(request, "Please select an employee.")
            return render(request, 'assets/assign_asset.html', {'asset': asset, 'employees': employees})
            
        try:
            employee = Employee.objects.get(id=employee_id, organization=request.user.organization, is_deleted=False)
        except Employee.DoesNotExist:
            messages.error(request, "Selected employee not found.")
            return render(request, 'assets/assign_asset.html', {'asset': asset, 'employees': employees})
            
        try:
            with transaction.atomic():
                AssetAssignment.objects.create(
                    organization=request.user.organization,
                    asset=asset,
                    employee=employee,
                    assigned_date=timezone.now().date(),
                    expected_return_date=expected_return_date,
                    condition_at_issue=condition_at_issue,
                    created_by=request.user
                )
                
                asset.status = 'ASSIGNED'
                asset.condition = condition_at_issue
                asset.save()
                
            messages.success(request, f"Asset assigned to {employee.first_name}.")
            return redirect('assets:inventory')
        except (ValueError, ValidationError) as e:
            messages.error(request, f"Validation Error: {e}")
        except Exception as e:
            messages.error(request, f"An unexpected error occurred while assigning the asset: {e}")
            
    return render(request, 'assets/assign_asset.html', {'asset': asset, 'employees': employees})

@login_required
def return_asset_view(request, assignment_id):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    assignment = get_object_or_404(AssetAssignment, id=assignment_id, organization=request.user.organization, status='ACTIVE')
    
    if request.method == 'POST':
        condition_at_return = request.POST.get('condition_at_return', 'GOOD')
        new_status = request.POST.get('new_status', 'AVAILABLE')
        
        try:
            with transaction.atomic():
                assignment.status = 'RETURNED'
                assignment.returned_date = timezone.now().date()
                assignment.condition_at_return = condition_at_return
                assignment.save()
                
                asset = assignment.asset
                asset.status = new_status
                asset.condition = condition_at_return
                asset.save()
                
            messages.success(request, "Asset returned successfully.")
            return redirect('assets:inventory')
        except Exception as e:
            messages.error(request, f"An error occurred while returning the asset: {e}")
            
    return render(request, 'assets/return_asset.html', {'assignment': assignment})

@login_required
def manage_requests_view(request):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    requests = AssetRequest.objects.filter(organization=request.user.organization).order_by('-created_at')
    return render(request, 'assets/manage_requests.html', {'requests': requests})

@login_required
def request_action_view(request, request_id):
    if not request.user.is_staff:
        return redirect('assets:my_assets')
        
    asset_req = get_object_or_404(AssetRequest, id=request_id, organization=request.user.organization)
    
    if request.method == 'POST':
        action = request.POST.get('action')
        
        try:
            if action == 'approve':
                asset_req.status = 'APPROVED'
                asset_req.resolved_by = request.user
                asset_req.resolved_at = timezone.now()
                asset_req.save()
                messages.success(request, "Request approved. Please assign an asset to fulfill it.")
                
            elif action == 'reject':
                asset_req.status = 'REJECTED'
                asset_req.rejection_reason = request.POST.get('rejection_reason', '').strip()
                asset_req.resolved_by = request.user
                asset_req.resolved_at = timezone.now()
                asset_req.save()
                messages.success(request, "Request rejected successfully.")
            else:
                messages.error(request, "Invalid action specified.")
        except Exception as e:
            messages.error(request, f"An error occurred while updating the request: {e}")
            
    return redirect('assets:manage_requests')

@login_required
def manage_categories_view(request):
    if not request.user.is_staff:
        return redirect('assets:my_assets')

    if request.method == 'POST':
        name = request.POST.get('name', '').strip()
        icon = request.POST.get('icon', 'fa-box').strip()
        
        if not name:
            messages.error(request, "Category name is required.")
            return redirect('assets:manage_categories')
            
        # Check across ALL records (including soft-deleted) using iexact
        existing_cat = AssetCategory.all_objects.filter(
            organization=request.user.organization, 
            name__iexact=name
        ).first()
        
        if existing_cat:
            if not existing_cat.is_deleted:
                messages.error(request, f"Category '{name}' already exists.")
                return redirect('assets:manage_categories')
            else:
                # Restore the soft-deleted category
                existing_cat.is_deleted = False
                existing_cat.is_active = True
                existing_cat.icon = icon
                existing_cat.updated_by = request.user
                existing_cat.save()
                messages.success(request, f"Category '{name}' has been restored.")
                return redirect('assets:manage_categories')
                
        try:
            AssetCategory.objects.create(
                organization=request.user.organization,
                name=name,
                icon=icon,
                created_by=request.user
            )
            messages.success(request, "Category added successfully.")
        except IntegrityError:
            messages.error(request, "A database conflict occurred. This category might already exist.")
        except Exception as e:
            messages.error(request, f"An unexpected error occurred: {e}")
            
        return redirect('assets:manage_categories')

    edit_category = None
    edit_id = request.GET.get('edit')
    if edit_id:
        edit_category = get_object_or_404(
            AssetCategory,
            id=edit_id,
            organization=request.user.organization,
        )

    categories = AssetCategory.objects.filter(
        organization=request.user.organization
    ).annotate(
        asset_count=Count('assets', filter=Q(assets__is_deleted=False), distinct=True),
        request_count=Count('requests', filter=Q(requests__is_deleted=False), distinct=True),
    ).order_by('name')

    return render(request, 'assets/manage_categories.html', {
        'categories': categories,
        'edit_category': edit_category,
    })


@login_required
def edit_category_view(request, category_id):
    if not request.user.is_staff:
        return redirect('assets:my_assets')

    category = get_object_or_404(
        AssetCategory,
        id=category_id,
        organization=request.user.organization,
    )

    if request.method != 'POST':
        return redirect(f"{reverse('assets:manage_categories')}?edit={category.id}")

    name = request.POST.get('name', '').strip()
    icon = request.POST.get('icon', 'fa-box').strip() or 'fa-box'

    if not name:
        messages.error(request, "Category name is required.")
        return redirect(f"{reverse('assets:manage_categories')}?edit={category.id}")

    duplicate = AssetCategory.all_objects.filter(
        organization=request.user.organization,
        name__iexact=name,
    ).exclude(id=category.id).first()
    if duplicate:
        messages.error(request, f"Another category named '{name}' already exists.")
        return redirect(f"{reverse('assets:manage_categories')}?edit={category.id}")

    try:
        category.name = name
        category.icon = icon
        category.updated_by = request.user
        category.save()
        messages.success(request, "Category updated successfully.")
    except IntegrityError:
        messages.error(request, "A database conflict occurred. This category name might already exist.")
        return redirect(f"{reverse('assets:manage_categories')}?edit={category.id}")
    except Exception as e:
        messages.error(request, f"An unexpected error occurred: {e}")
        return redirect(f"{reverse('assets:manage_categories')}?edit={category.id}")

    return redirect('assets:manage_categories')


@login_required
def delete_category_view(request, category_id):
    if not request.user.is_staff:
        return redirect('assets:my_assets')

    category = get_object_or_404(
        AssetCategory,
        id=category_id,
        organization=request.user.organization,
    )

    if request.method != 'POST':
        messages.error(request, "Invalid delete request.")
        return redirect('assets:manage_categories')

    category.is_deleted = True
    category.is_active = False
    category.deleted_at = timezone.now()
    category.deleted_by = request.user
    category.save(update_fields=['is_deleted', 'is_active', 'deleted_at', 'deleted_by', 'updated_at'])
    messages.success(request, f"Category '{category.name}' deleted successfully. Existing asset history is preserved.")

    return redirect('assets:manage_categories')


# --- Employee Views ---

@login_required
def my_assets_view(request):
    employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization).first()
    if not employee:
        messages.error(request, "Employee profile not found.")
        return redirect('home')
        
    assignments = AssetAssignment.objects.filter(employee=employee, status='ACTIVE').select_related('asset', 'asset__category')
    requests = AssetRequest.objects.filter(employee=employee).order_by('-created_at')
    
    context = {
        'assignments': assignments,
        'requests': requests,
    }
    return render(request, 'assets/my_assets.html', context)

@login_required
def request_asset_view(request):
    employee = Employee.objects.filter(email=request.user.email, organization=request.user.organization, is_active=True, is_deleted=False).first()
    if not employee:
        messages.error(request, "Employee profile not found or inactive.")
        return redirect('home')
        
    categories = AssetCategory.objects.filter(organization=request.user.organization)
    
    if request.method == 'POST':
        category_id = request.POST.get('category_id')
        reason = request.POST.get('reason', '').strip()
        priority = request.POST.get('priority', 'MEDIUM')
        
        if not category_id or not reason:
            messages.error(request, "Please specify a category and a reason for your request.")
            return render(request, 'assets/request_asset.html', {'categories': categories})
            
        try:
            category = get_object_or_404(AssetCategory, id=category_id, organization=request.user.organization)
            
            # Optional UX warning: check if they already have a pending request for the exact same category
            if AssetRequest.objects.filter(
                organization=request.user.organization,
                employee=employee,
                category=category,
                status='PENDING'
            ).exists():
                messages.warning(request, f"You already have a pending request for a '{category.name}'.")
                return redirect('assets:my_assets')
                
            AssetRequest.objects.create(
                organization=request.user.organization,
                employee=employee,
                category=category,
                reason=reason,
                priority=priority,
                created_by=request.user
            )
            messages.success(request, "Asset request submitted successfully.")
            return redirect('assets:my_assets')
        except Exception as e:
            messages.error(request, f"An error occurred while submitting your request: {e}")
            
    return render(request, 'assets/request_asset.html', {'categories': categories})
