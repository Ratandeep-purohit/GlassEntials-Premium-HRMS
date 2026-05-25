# Project Fix Checklist

This checklist is based on the current code review of the Django HRMS project.
Fix these in priority order.

## Priority 1: Access Control

- Add `@login_required` and staff/admin checks to employee management views:
  - `employees/views.py:133` `department_view`
  - `employees/views.py:190` `delete_department`
  - `employees/views.py:202` `toggle_department_status`
  - `employees/views.py:220` `designation_view`
  - `employees/views.py:284` `delete_designation`
  - `employees/views.py:296` `toggle_designation_status`
  - `employees/views.py:312` `add_employee`

- Restrict sensitive employee record actions to staff/admin:
  - `employees/views.py:389` `toggle_employee_status`
  - `employees/views.py:401` `delete_employee`
  - `employees/views.py:413` `view_employee`
  - `employees/views.py:425` `edit_employee`
  - `employees/views.py:501` `export_employees_csv`
  - `employees/views.py:557` `export_employees_excel`
  - `employees/views.py:694` `bulk_import`

- Add login and staff/admin checks to attendance shift management:
  - `attendance/views.py:79` `create_shift_view`
  - `attendance/views.py:176` `assign_shift_view`

- Prefer a shared decorator/helper for HR/admin-only views so the rule is consistent across apps.

## Priority 2: Leave Workflow Bug

- Fix references to `employee.manager.user`.
- `Employee.manager` is a foreign key to another `Employee`, not a `CustomUser`.
- Affected locations:
  - `leaves/views.py:222`
  - `leaves/views.py:240`
  - `leaves/views.py:459`
  - `leaves/views.py:539`

Suggested approach:
- Add a reliable way to resolve the manager's user account, such as matching by `manager.email` and `organization`.
- Consider adding an explicit `user` foreign key on `Employee` if the app needs stable user-to-employee relationships.

## Priority 3: Tenant Isolation

- Remove `Q(organization=organization) | Q(organization__isnull=True)` from sensitive payroll queries unless the model is truly global master data.
- Review these areas first:
  - Payroll runs
  - Payslips
  - Salary structures
  - Employee loans
  - Arrears
  - Employee records

- Keep `organization__isnull=True` only for safe global configuration tables, if any.
- Add tests proving one organization's payroll data is not visible to another organization.

## Priority 4: Repository Hygiene and Privacy

- Add a `.gitignore`.
- Stop tracking generated Python cache files:
  - `__pycache__/`
  - `*.pyc`

- Stop tracking uploaded HR documents and local media:
  - `media/aadhaar_cards/`
  - `media/pan_cards/`
  - `media/resumes/`
  - `media/profile_imgs/`

- Remove already-tracked sensitive files from Git history or rotate the repository if the documents are real.
- Keep `.env` untracked and use `.env.example` for safe sample values.

## Priority 5: Public Registration Flow

- Review `accounts/views.py:29` `register_view`.
- Currently, public organization creation grants:
  - `is_approved = True`
  - `is_staff = True`

- If this project is public-facing, add one of:
  - invite-only organization creation
  - email/domain verification
  - superadmin approval
  - a disabled-by-default setting for self-service tenant creation

## Priority 6: Production Settings

- Confirm production runs with:
  - `DJANGO_DEBUG=False`
  - strong `DJANGO_SECRET_KEY`
  - correct `DJANGO_ALLOWED_HOSTS`
  - secure cookies enabled
  - HTTPS redirect enabled
  - HSTS configured only after HTTPS is confirmed stable

- `python manage.py check --deploy` currently warns when run with the local debug environment.

## Priority 7: Tests to Add

- Non-staff users cannot access employee management, exports, imports, shift creation, or shift assignment.
- Employees cannot view or edit other employees' private HR records.
- Leave application works when an employee has a manager.
- Payroll data from Organization A is invisible to users from Organization B.
- Public registration cannot create unrestricted staff users unless explicitly allowed.

## Verification Commands

Run after fixes:

```powershell
python manage.py test
python manage.py check --deploy
```

