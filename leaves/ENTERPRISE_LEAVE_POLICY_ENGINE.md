# Enterprise Leave Policy Engine Blueprint

This document defines the target architecture for replacing the current basic leave setup form with a production-grade HRMS Leave Management Engine.

The design is intended for the existing Django project and current modules:

- `employees`
- `attendance`
- `payroll`
- `home` notifications
- `leaves`

The goal is not to store a leave name and max balance. The goal is to run policy-driven eligibility, accrual, validation, workflow, attendance sync, payroll impact, balance accounting, audit, and analytics.

## 1. Product Model

The Leaves module should become a policy workbench with these surfaces:

- Leave Policy Master
- Accrual Rules
- Eligibility Rules
- Restriction Rules
- Sandwich and Clubbing Rules
- Carry Forward and Expiry Rules
- Encashment Rules
- Attachment and Proof Rules
- Approval Workflow Designer
- Holiday Calendar Mapping
- Attendance Sync Rules
- Payroll Impact Rules
- Balance Ledger and Snapshots
- Audit Logs
- Notifications and Escalations
- Analytics and Reports

The existing "Create Leave" page should become a multi-section policy editor. The existing "Assign Leaves" page should become a balance assignment and recalculation console.

## 2. Core Domain Principles

1. Policy is versioned.
   A leave request must always point to the policy version used during application.

2. Balance changes are ledger-based.
   `LeaveBalance` is the current state. `LeaveTransaction` is the source of truth for every movement.

3. Approval is workflow-driven.
   The request does not hardcode manager or HR logic. A workflow resolver builds approval steps from policy, department, role, and employee structure.

4. Attendance and payroll integration are event-driven.
   Leave approval emits integration events, then attendance/payroll consume those events safely.

5. Validation is centralized.
   Leave application should pass through one validation engine, not scattered checks in views.

6. All important actions are auditable.
   Policy changes, balance changes, approvals, proof reviews, payroll adjustments, and attendance sync must write audit records.

## 3. Target Django Package Layout

```text
leaves/
  models.py
  urls.py
  views.py
  admin.py
  services/
    policy_resolver.py
    eligibility_engine.py
    calendar_engine.py
    restriction_engine.py
    balance_engine.py
    accrual_engine.py
    carry_forward_engine.py
    workflow_engine.py
    attachment_engine.py
    attendance_integration.py
    payroll_integration.py
    notification_service.py
    audit_service.py
    analytics_service.py
  selectors/
    policies.py
    balances.py
    requests.py
  api/
    urls.py
    views.py
    serializers.py
  tasks/
    accrue_leaves.py
    process_carry_forward.py
    expire_leaves.py
    send_leave_reminders.py
  templates/leaves/
    policy_workbench.html
    policy_detail.html
    assign_balances.html
    employee_dashboard.html
    approval_timeline.html
    analytics.html
```

Views should become thin. They should call services. Services should own business logic.

## 4. Database Schema

The current models should be expanded or replaced gradually. Where possible, migrate existing data into the new tables rather than deleting it.

### 4.1 LeaveCategory

Stores grouping and reporting classification.

Fields:

- `organization`
- `name`
- `code`
- `description`
- `color`
- `is_paid_category`
- `is_active`

Examples:

- Paid Leave
- Unpaid Leave
- Statutory Leave
- Optional Holiday
- Comp Off
- Work From Home

### 4.2 LeavePolicy

This becomes the policy master, not just max balance.

Fields:

- `organization`
- `category`
- `name`
- `code`
- `description`
- `color_tag`
- `financial_year_start_month`
- `effective_from`
- `effective_to`
- `version`
- `status`: `DRAFT`, `ACTIVE`, `INACTIVE`, `ARCHIVED`
- `is_paid`
- `is_statutory`
- `allow_negative_balance`
- `negative_balance_limit`
- `is_requestable`
- `is_system_generated`
- `created_by`
- `updated_by`

Constraints:

- Unique active policy per `organization + code + version`
- No overlapping effective windows for the same code unless explicitly versioned

### 4.3 LeaveAccrualRule

Defines how leave is earned.

Fields:

- `policy`
- `frequency`: `NONE`, `MONTHLY`, `QUARTERLY`, `HALF_YEARLY`, `YEARLY`, `JOINING_DATE`, `MANUAL`
- `accrual_day`
- `accrual_month`
- `accrual_rate`
- `prorate_on_joining`
- `prorate_on_exit`
- `max_yearly_accrual`
- `max_balance_cap`
- `rounding_mode`: `NONE`, `UP`, `DOWN`, `NEAREST_HALF`, `NEAREST_FULL`
- `enabled`

Example:

- Earned Leave accrues `1.5` days on the first day of every month.

### 4.4 LeaveCarryForwardRule

Fields:

- `policy`
- `is_allowed`
- `max_carry_forward_days`
- `expiry_month`
- `expiry_day`
- `encash_remaining`
- `lapse_remaining`
- `enabled`

Example:

- Carry forward max 10 days. Expire on March 31. Encash balance above 10.

### 4.5 LeaveEligibilityRule

Rules that decide who can use a policy.

Fields:

- `policy`
- `gender`: nullable
- `departments`: many-to-many
- `designations`: many-to-many
- `employment_types`: JSON/list
- `locations`: many-to-many or normalized branch/location relation
- `min_service_days`
- `probation_allowed`
- `confirmation_required`
- `employee_filter_mode`: `INCLUDE`, `EXCLUDE`
- `specific_employees`: many-to-many
- `enabled`

Examples:

- Maternity Leave only for female employees.
- Earned Leave only after 180 days.
- Contract employees excluded.

### 4.6 LeaveRestrictionRule

Validation limits.

Fields:

- `policy`
- `min_duration`
- `max_duration`
- `max_consecutive_days`
- `min_gap_between_requests`
- `max_requests_per_month`
- `max_requests_per_year`
- `backdate_allowed`
- `max_backdate_days`
- `future_date_allowed`
- `max_future_days`
- `block_during_payroll_lock`
- `block_month_end`
- `blackout_dates`: JSON or normalized `LeaveBlackoutPeriod`
- `enabled`

### 4.7 LeaveDurationRule

Half-day and hourly rules.

Fields:

- `policy`
- `allow_full_day`
- `allow_half_day`
- `allow_hourly`
- `minimum_hourly_unit_minutes`
- `maximum_hourly_duration_minutes`
- `shift_aware`
- `allowed_sessions`: JSON, e.g. `FULL`, `FIRST_HALF`, `SECOND_HALF`, `HOURLY`

### 4.8 LeaveSandwichRule

Weekend/holiday and clubbing rules.

Fields:

- `policy`
- `count_weekends_between_leave`
- `count_holidays_between_leave`
- `count_prefix_weekend`
- `count_suffix_weekend`
- `count_prefix_holiday`
- `count_suffix_holiday`
- `blocked_clubbing_policies`: many-to-many to `LeavePolicy`
- `enabled`

Example:

- Friday and Monday Casual Leave counts Saturday/Sunday.
- Sick Leave cannot be clubbed with Casual Leave.

### 4.9 LeaveProofRule

Attachment and proof review rules.

Fields:

- `policy`
- `proof_required`
- `required_after_days`
- `allowed_file_types`
- `max_file_size_mb`
- `requires_manual_review`
- `reviewer_role`: `MANAGER`, `HR`, `PAYROLL_ADMIN`
- `enabled`

### 4.10 LeaveBalance

Current balance state.

Fields:

- `employee`
- `policy`
- `year`
- `opening_balance`
- `accrued_balance`
- `consumed_balance`
- `reserved_balance`
- `carry_forward_balance`
- `expired_balance`
- `encashed_balance`
- `adjusted_balance`
- `current_balance`
- `future_approved_balance`
- `last_recalculated_at`

Constraint:

- Unique `employee + policy + year`

### 4.11 LeaveTransaction

Ledger of every balance movement.

Fields:

- `organization`
- `employee`
- `policy`
- `leave_request`
- `transaction_type`: `OPENING`, `ACCRUAL`, `RESERVE`, `CONSUME`, `RELEASE`, `CARRY_FORWARD`, `EXPIRE`, `ENCASH`, `ADJUSTMENT`, `LOP`
- `amount`
- `balance_before`
- `balance_after`
- `effective_date`
- `source`: `SYSTEM`, `ADMIN`, `PAYROLL`, `ATTENDANCE`
- `description`
- `created_by`

This table should replace `LeaveAccrualLog` over time.

### 4.12 LeaveRequest

Transactional leave request.

Additional target fields:

- `policy`
- `policy_version`
- `request_number`
- `applied_at`
- `start_date`
- `end_date`
- `start_time`
- `end_time`
- `duration_type`: `FULL_DAY`, `HALF_DAY`, `HOURLY`
- `session_type`
- `calculated_days`
- `payable_days`
- `lop_days`
- `status`: `DRAFT`, `PENDING`, `APPROVED`, `REJECTED`, `CANCELLED`, `WITHDRAWN`, `ESCALATED`
- `reason`
- `current_workflow_step`
- `attendance_sync_status`
- `payroll_sync_status`
- `created_by`

### 4.13 LeaveWorkflow

Workflow definition.

Fields:

- `organization`
- `name`
- `policy`: nullable
- `department`: nullable
- `is_default`
- `is_active`
- `escalation_enabled`
- `auto_approval_enabled`

### 4.14 LeaveWorkflowStep

Workflow step definition.

Fields:

- `workflow`
- `order`
- `approver_type`: `REPORTING_MANAGER`, `DEPARTMENT_HEAD`, `HR`, `SPECIFIC_USER`, `ROLE`, `AUTO_APPROVE`
- `specific_user`
- `role_name`
- `approval_mode`: `ANY_ONE`, `ALL`
- `sla_hours`
- `escalate_to_type`
- `escalate_to_user`
- `delegation_allowed`

### 4.15 LeaveApproval

Runtime approval action.

Fields:

- `leave_request`
- `workflow_step`
- `approver`
- `status`: `PENDING`, `APPROVED`, `REJECTED`, `SKIPPED`, `ESCALATED`, `DELEGATED`
- `comments`
- `action_at`
- `delegated_to`

### 4.16 LeaveAttachment

Fields:

- `leave_request`
- `file`
- `file_name`
- `file_type`
- `file_size`
- `uploaded_by`
- `review_status`: `PENDING`, `APPROVED`, `REJECTED`
- `reviewed_by`
- `reviewed_at`
- `reviewer_comments`

### 4.17 LeaveEncashment

Fields:

- `employee`
- `policy`
- `year`
- `days`
- `rate_per_day`
- `gross_amount`
- `taxable_amount`
- `payroll_run`
- `status`: `DRAFT`, `APPROVED`, `POSTED_TO_PAYROLL`, `CANCELLED`

### 4.18 LeaveCarryForwardLog

Fields:

- `employee`
- `policy`
- `from_year`
- `to_year`
- `eligible_days`
- `carried_forward_days`
- `expired_days`
- `encashed_days`
- `processed_at`

### 4.19 LeaveAuditLog

Fields:

- `organization`
- `entity_type`
- `entity_id`
- `action`
- `old_value`
- `new_value`
- `performed_by`
- `performed_at`
- `ip_address`
- `user_agent`

### 4.20 HolidayCalendar and Holiday

`HolidayCalendar` fields:

- `organization`
- `name`
- `location`
- `branch`
- `year`
- `is_default`
- `is_active`

`Holiday` fields:

- `calendar`
- `name`
- `date`
- `holiday_type`: `NATIONAL`, `REGIONAL`, `COMPANY`, `OPTIONAL`
- `is_paid`
- `is_optional`

## 5. Engines and Backend Logic

### 5.1 Policy Resolver

Responsibility:

- Resolve the effective policy for an employee and date.
- Enforce version and effective date.
- Return all linked rule objects.

Pseudo flow:

```text
resolve(employee, leave_policy_code, date):
  find active policy where:
    organization matches
    code matches
    effective_from <= date
    effective_to is null or effective_to >= date
  ensure eligibility rules match employee
  return PolicyContext(policy, rules, employee, date)
```

### 5.2 Eligibility Engine

Checks:

- Gender
- Department
- Designation
- Employment type
- Location/branch
- Shift
- Probation status
- Confirmation status
- Minimum service days
- Employee-specific include/exclude

Output:

- `eligible: bool`
- `errors: list`
- `warnings: list`

### 5.3 Calendar Engine

Calculates leave duration.

Inputs:

- Employee
- Shift
- Holiday calendar
- Weekly offs
- Start/end dates
- Start/end time
- Duration type
- Sandwich rules

Outputs:

- `calendar_days`
- `working_days`
- `paid_days`
- `lop_days`
- `sandwich_days`
- `holiday_days`
- `weekend_days`

### 5.4 Restriction Engine

Validates:

- Overlapping leave requests
- Minimum/maximum duration
- Consecutive leave limit
- Gap between leaves
- Monthly/yearly request cap
- Backdate and future-date rules
- Blackout period
- Month-end restriction
- Payroll lock restriction
- Clubbing restrictions
- Proof rules

### 5.5 Balance Engine

Operations:

- `get_balance(employee, policy, year)`
- `reserve(request)`
- `consume(request)`
- `release(request)`
- `adjust(employee, policy, amount, reason)`
- `recalculate(employee, policy, year)`
- `snapshot(employee, year)`

Important:

- Use database transactions and row locks for concurrent applications.
- Reserve balance when request is submitted.
- Consume balance only on final approval.
- Release balance on rejection/withdrawal/cancellation before approval.
- Credit balance on cancellation after approval.

### 5.6 Accrual Engine

Scheduler:

- Daily job checks due accrual rules.
- Monthly/quarterly/yearly accruals are posted through `LeaveTransaction`.
- Joining-date based accrual prorates for mid-period joiners.
- Exiting employee accrual is prorated until last working day.

Pseudo flow:

```text
run_accrual(process_date):
  for each active policy with accrual enabled:
    if accrual_due(policy, process_date):
      for each eligible employee:
        amount = calculate_accrual(employee, policy, process_date)
        cap amount by yearly limit and balance cap
        BalanceEngine.adjust(... transaction_type=ACCRUAL)
```

### 5.7 Carry Forward Engine

Year-end process:

```text
process_year_end(year):
  for each employee balance:
    rule = policy.carry_forward_rule
    if not allowed:
      expire full remaining balance
    else:
      carry = min(remaining, max_carry_forward_days)
      extra = remaining - carry
      if encash_remaining:
        create encashment for extra
      if lapse_remaining:
        expire extra
      create next year balance opening with carry
      create carry forward log
```

### 5.8 Workflow Engine

Responsibilities:

- Resolve workflow for request.
- Create runtime approval rows.
- Advance request after each action.
- Support auto approval, escalation, and delegation.

Flow:

```text
submit_request(request):
  workflow = resolve_workflow(request.employee, request.policy)
  steps = build_steps(workflow)
  if first step auto approve:
    approve automatically
  else:
    request.status = PENDING
    notify first approver

approve_step(request, approver):
  mark current step approved
  if next step exists:
    move to next step
    notify next approver
  else:
    request.status = APPROVED
    BalanceEngine.consume(request)
    AttendanceIntegration.mark_leave(request)
    PayrollIntegration.register_leave_event(request)
```

### 5.9 Attachment Engine

Checks:

- Required proof after X days
- File type
- File size
- Malware scan hook
- Reviewer approval

### 5.10 Attendance Integration

On final approval:

- Create attendance leave marker for each affected work date.
- Prevent conflicts with already present/punched attendance.
- Adjust late/absent marks.
- Link leave request to attendance records.
- Support comp-off generation for approved worked holidays/weekends.

Required integration contract:

```text
AttendanceLeaveEvent:
  employee
  leave_request
  date
  session
  paid_status
  source = LEAVE_MODULE
```

### 5.11 Payroll Integration

On payroll run:

- Pull approved leave events for payroll month.
- Calculate paid leave days.
- Calculate LOP days.
- Apply negative balance deduction if enabled.
- Add encashment earnings.
- Add final settlement leave encashment.
- Lock leave changes after payroll finalization.

Required integration contract:

```text
PayrollLeaveImpact:
  employee
  payroll_period
  paid_leave_days
  lop_days
  encashment_days
  encashment_amount
  adjustment_amount
```

## 6. End-to-End Workflows

### 6.1 Admin Creates Policy

1. HR opens Leave Policy Workbench.
2. Enters policy master details.
3. Configures eligibility.
4. Configures accrual.
5. Configures restrictions.
6. Configures carry forward and encashment.
7. Configures proof rules.
8. Maps workflow.
9. Saves as Draft.
10. Activates policy after validation.
11. Audit log records old/new policy data.

### 6.2 Employee Applies Leave

1. Employee selects leave policy.
2. System shows real-time balance and policy rules.
3. Employee selects dates/session/hours.
4. Calendar engine calculates duration.
5. Eligibility engine validates employee eligibility.
6. Restriction engine validates policy constraints.
7. Balance engine checks available balance.
8. Proof engine validates attachment requirement.
9. Balance is reserved.
10. Workflow is created.
11. Approver notification is sent.

### 6.3 Approver Approves Leave

1. Approver sees request, balance impact, attendance conflicts, and policy violations.
2. Approver approves/rejects.
3. Workflow engine advances.
4. On final approval:
   - Balance moves from reserved to consumed.
   - Attendance is marked as leave.
   - Payroll leave event is recorded.
   - Employee is notified.
   - Audit log is written.

### 6.4 Cancellation

Before approval:

- Release reserved balance.
- Mark request cancelled/withdrawn.

After approval:

- Route cancellation through approval workflow.
- Reverse attendance markers.
- Reverse payroll event if payroll is not locked.
- If payroll is locked, create next-period adjustment.
- Credit balance back.

### 6.5 Payroll Lock

When payroll is processing or finalized:

- Block backdated leave changes for locked period.
- Allow HR override only if adjustment entry is generated.
- Write audit log with override reason.

## 7. API Design

If Django REST Framework is added, use these endpoints. Without DRF, the same contracts can be implemented as class-based JSON views.

Policy APIs:

- `GET /api/leaves/policies/`
- `POST /api/leaves/policies/`
- `GET /api/leaves/policies/{id}/`
- `PATCH /api/leaves/policies/{id}/`
- `POST /api/leaves/policies/{id}/activate/`
- `POST /api/leaves/policies/{id}/archive/`

Rule APIs:

- `POST /api/leaves/policies/{id}/accrual-rule/`
- `POST /api/leaves/policies/{id}/eligibility-rule/`
- `POST /api/leaves/policies/{id}/restriction-rule/`
- `POST /api/leaves/policies/{id}/carry-forward-rule/`
- `POST /api/leaves/policies/{id}/proof-rule/`
- `POST /api/leaves/policies/{id}/sandwich-rule/`

Employee APIs:

- `GET /api/leaves/balances/`
- `GET /api/leaves/history/`
- `POST /api/leaves/apply/`
- `POST /api/leaves/{id}/cancel/`
- `POST /api/leaves/{id}/attachments/`
- `GET /api/leaves/team-availability/`

Approval APIs:

- `GET /api/leaves/approvals/pending/`
- `POST /api/leaves/{id}/approve/`
- `POST /api/leaves/{id}/reject/`
- `POST /api/leaves/{id}/delegate/`

Scheduler APIs:

- `POST /api/leaves/schedulers/accrual/run/`
- `POST /api/leaves/schedulers/carry-forward/run/`
- `POST /api/leaves/schedulers/expiry/run/`

Integration APIs:

- `GET /api/leaves/payroll-impact/{period}/`
- `POST /api/leaves/encashment/`
- `POST /api/leaves/holiday-sync/`
- `GET /api/leaves/attendance-events/`

## 8. UI/UX Design

### 8.1 Admin Leave Policy Workbench

Replace the basic form with tabs or collapsible sections:

- Overview
- Eligibility
- Accrual
- Restrictions
- Half Day and Hourly
- Sandwich and Clubbing
- Carry Forward
- Encashment
- Proofs
- Workflow
- Payroll Impact
- Audit

UI elements:

- Policy cards with status and color tag
- Version badge
- Effective date timeline
- Accrual preview
- Balance impact preview
- Workflow visualizer
- Rule health checklist
- Payroll impact preview
- Activation readiness score

### 8.2 Assign Balances Console

Features:

- Select employees by department/designation/location
- Bulk assign opening balance
- Add/manual adjustment
- Import from CSV
- Recalculate balance
- Preview affected employees before submit
- Ledger view after submit

### 8.3 Employee Dashboard

Features:

- Balance cards
- Upcoming holidays
- Team availability
- Leave history
- Approval timeline
- Policy rule summary
- Attachment status
- Payroll impact warning for LOP

### 8.4 Approver Dashboard

Features:

- Pending approvals
- Policy violations
- Team availability
- Overlap warnings
- Attendance conflict warnings
- Balance impact
- One-click approve/reject
- Delegation and escalation status

## 9. Validation Rules

Application validations:

- Employee profile exists.
- Policy is active and effective.
- Employee is eligible.
- Dates are valid.
- Date range does not overlap existing pending/approved leave.
- Duration satisfies policy.
- Balance is available or negative balance is allowed.
- Proof is attached when required.
- Payroll period is not locked.
- Blackout period not violated.
- Clubbing rules not violated.
- Backdate/future limits not violated.
- Holiday/weekend sandwich rules are applied.

Approval validations:

- Approver is authorized.
- Request is still pending.
- Payroll period is not locked, or override is logged.
- Proof status is acceptable if mandatory.
- No attendance conflict exists unless override is allowed.

Balance validations:

- No negative balance unless policy allows.
- Ledger transaction is immutable.
- Balance update happens in a database transaction.
- Recalculation uses ledger as source of truth.

## 10. Edge Cases

- Employee joins mid-month.
- Employee exits mid-cycle.
- Employee applies across financial years.
- Employee changes department after applying.
- Policy changes after request submission.
- Two requests are submitted at the same time.
- Leave overlaps payroll lock.
- Leave overlaps attendance punch.
- Optional holiday is claimed then cancelled.
- Weekend/holiday sandwich crosses month boundary.
- Half-day leave on short shift.
- Hourly leave during break hours.
- Manager is missing.
- Manager account is inactive.
- HR rejects proof after manager approval.
- Payroll has already processed approved leave.
- Employee has negative balance.
- Carry-forward expiry passes before employee uses carried leave.
- Encashment is approved but payroll is not finalized.
- Bulk import has duplicate employees.
- Policy is deactivated while pending requests exist.

## 11. Notifications

Events:

- Leave request submitted
- Approval pending
- Leave approved
- Leave rejected
- Leave cancelled
- Proof required
- Proof rejected
- Balance low
- Carry-forward expiry reminder
- Approval SLA breached
- Escalation triggered
- Payroll adjustment generated

Channels:

- In-app notification now
- Email next
- SMS/WhatsApp-ready through provider adapter

Notification service interface:

```text
notify(event_type, actor, target_users, payload, channels)
```

## 12. Audit Strategy

Every write operation should call `AuditService.record(...)`.

Audit scope:

- Policy create/update/activate/archive
- Rule changes
- Leave apply/modify/cancel
- Approval actions
- Proof upload/review
- Balance reserve/consume/release/adjust
- Accrual run
- Carry-forward run
- Encashment posting
- Payroll override
- Attendance sync

## 13. Analytics

Admin dashboard should show:

- Leave utilization by policy
- Leave utilization by department
- Monthly leave trend
- Pending approval count
- Approval SLA breach count
- LOP report
- Leave liability report
- Encashment liability
- High absentee alerts
- Team availability heatmap

Metrics source:

- `LeaveRequest`
- `LeaveTransaction`
- `LeaveBalance`
- `LeaveApproval`
- Payroll impact table
- Attendance events

## 14. Production Implementation Plan

### Phase 1: Schema Foundation

Add or migrate to:

- `LeaveCategory`
- Expanded `LeavePolicy`
- `LeaveAccrualRule`
- `LeaveCarryForwardRule`
- `LeaveEligibilityRule`
- `LeaveRestrictionRule`
- `LeaveDurationRule`
- `LeaveSandwichRule`
- `LeaveProofRule`
- `LeaveTransaction`
- `LeaveAttachment`
- `LeaveWorkflow`
- `LeaveWorkflowStep`
- `LeaveApproval`
- `LeaveEncashment`
- `LeaveCarryForwardLog`
- `LeaveAuditLog`
- `HolidayCalendar`

Data migration:

- Existing `LeaveType` becomes `LeavePolicy` or maps into `LeaveCategory + LeavePolicy`.
- Existing `LeaveAccrualLog` maps into `LeaveTransaction`.
- Existing `ApprovalWorkflow` maps into `LeaveApproval` runtime rows.

### Phase 2: Service Engines

Implement:

- Policy resolver
- Eligibility engine
- Calendar engine
- Restriction engine
- Balance engine
- Workflow engine
- Audit service

Move logic out of `views.py`.

### Phase 3: Policy Workbench UI

Replace `manage_leave_types.html` with enterprise policy workbench:

- Overview
- Eligibility
- Accrual
- Restrictions
- Carry forward
- Proof
- Workflow
- Payroll

### Phase 4: Employee Apply Flow

Update apply modal/page:

- Policy selector
- Balance preview
- Duration calculator
- Rule summary
- Attachment validation
- Payroll impact warning
- Approval timeline preview

### Phase 5: Accrual and Carry Forward Automation

Build management commands:

- `run_leave_accrual`
- `process_leave_carry_forward`
- `expire_leave_balances`
- `send_leave_expiry_reminders`

Use scheduled task runner later.

### Phase 6: Attendance and Payroll Integration

Attendance:

- Create leave attendance events after final approval.
- Detect conflicts.
- Reverse events on cancellation.

Payroll:

- Produce monthly leave impact data.
- Support LOP.
- Support encashment.
- Enforce payroll lock.

### Phase 7: APIs

Add REST/JSON endpoints for:

- Policy management
- Leave application
- Approval
- Balance
- Scheduler
- Payroll impact
- Team availability

### Phase 8: Analytics

Build dashboards for:

- Utilization
- Trends
- Leave liability
- Absenteeism
- Pending approvals
- SLA breaches

## 15. Immediate Next Build Tasks

Recommended next implementation order:

1. Replace the current Create Leave form with a tabbed Policy Workbench UI.
2. Add new schema models and migrations.
3. Implement `BalanceEngine` and `LeaveTransaction`.
4. Refactor apply/approve/cancel views to use `BalanceEngine`.
5. Add workflow definition tables and `WorkflowEngine`.
6. Add accrual/carry-forward commands using the new ledger.
7. Add payroll and attendance integration events.
8. Add API layer.
9. Add analytics dashboard.

This order avoids building UI that cannot be backed by real policy logic.

## 16. Acceptance Criteria

The module is enterprise-ready when:

- HR can create versioned policies with rules.
- Employees see only eligible policies.
- Leave duration is calculated using shifts, holidays, weekends, and sandwich rules.
- Leave can be reserved, approved, rejected, cancelled, and recalculated accurately.
- Approval flow is configurable.
- Accrual runs automatically and writes ledger transactions.
- Carry-forward, expiry, and encashment are automated.
- Attendance and payroll receive approved leave events.
- Payroll locks prevent unsafe historical edits.
- Every critical action has an audit record.
- Admin can view analytics and leave liability.
