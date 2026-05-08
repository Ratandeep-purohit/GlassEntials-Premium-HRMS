import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_customuser_is_approved"),
        ("employees", "0003_department_organization_designation_organization_and_more"),
        ("leaves", "0002_remove_leaverequest_approval_date_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [

        # ── 1. LeaveType – add new fields ──────────────────────────────────
        migrations.AddField(
            model_name="leavetype",
            name="is_statutory",
            field=models.BooleanField(default=False),
        ),

        # ── 2. LeaveBalance – add new columns (keep old ones for safety) ───
        migrations.AddField(
            model_name="leavebalance",
            name="current_balance",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=5),
        ),
        migrations.AddField(
            model_name="leavebalance",
            name="used_balance",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=5),
        ),
        migrations.AddField(
            model_name="leavebalance",
            name="pending_balance",
            field=models.DecimalField(decimal_places=2, default=0.0, max_digits=5),
        ),

        # ── 3. LeaveRequest – rename session → session_type ────────────────
        migrations.RenameField(
            model_name="leaverequest",
            old_name="session",
            new_name="session_type",
        ),

        # Update status choices to include DRAFT
        migrations.AlterField(
            model_name="leaverequest",
            name="status",
            field=models.CharField(
                choices=[
                    ("DRAFT", "Draft"),
                    ("PENDING", "Pending Approval"),
                    ("MANAGER_APPROVED", "Approved by Manager"),
                    ("APPROVED", "Fully Approved"),
                    ("REJECTED", "Rejected"),
                    ("CANCELLED", "Cancelled"),
                ],
                default="PENDING",
                max_length=20,
            ),
        ),

        # ── 4. New table: Location ─────────────────────────────────────────
        migrations.CreateModel(
            name="Location",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("name", models.CharField(max_length=100)),
                ("timezone", models.CharField(default="UTC", max_length=50)),
                ("country_code", models.CharField(help_text="ISO 3166-1 alpha-2", max_length=2)),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_deleted", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="%(class)s_records", to="accounts.organization")),
            ],
            options={"abstract": False},
        ),

        # ── 5. Update Holiday to FK to Location ───────────────────────────
        migrations.AddField(
            model_name="holiday",
            name="location_fk",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="leaves.location"),
        ),

        # ── 6. New table: LeavePolicy ──────────────────────────────────────
        migrations.CreateModel(
            name="LeavePolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("accrual_rate", models.DecimalField(decimal_places=2, help_text="Days accrued per month", max_digits=5)),
                ("max_balance", models.DecimalField(decimal_places=2, max_digits=5)),
                ("carry_forward_limit", models.DecimalField(decimal_places=2, max_digits=5)),
                ("min_service_days", models.PositiveIntegerField(default=0)),
                ("sandwich_rule", models.BooleanField(default=False)),
                ("requires_attachment", models.BooleanField(default=False)),
                ("attachment_threshold_days", models.PositiveIntegerField(default=3)),
                ("leave_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="policies", to="leaves.leavetype")),
                ("organization", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="%(class)s_records", to="accounts.organization")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_deleted", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"abstract": False},
        ),

        # ── 7. New table: ApprovalWorkflow ─────────────────────────────────
        migrations.CreateModel(
            name="ApprovalWorkflow",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("sequence_order", models.PositiveIntegerField()),
                ("status", models.CharField(choices=[("PENDING", "Pending"), ("APPROVED", "Approved"), ("REJECTED", "Rejected")], default="PENDING", max_length=20)),
                ("action_date", models.DateTimeField(blank=True, null=True)),
                ("comments", models.TextField(blank=True)),
                ("leave_request", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="workflow_steps", to="leaves.leaverequest")),
                ("approver", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ("organization", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="%(class)s_records", to="accounts.organization")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_deleted", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["sequence_order"], "abstract": False},
        ),

        # ── 8. New table: LeaveAccrualLog ──────────────────────────────────
        migrations.CreateModel(
            name="LeaveAccrualLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("is_deleted", models.BooleanField(db_index=True, default=False)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=5)),
                ("action_type", models.CharField(choices=[("ACCRUAL", "Automated Accrual"), ("MANUAL", "Manual Adjustment"), ("CARRY_FORWARD", "Year-end Carry Forward"), ("ENCASHMENT", "Leave Encashment")], max_length=20)),
                ("description", models.TextField(blank=True)),
                ("employee", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="employees.employee")),
                ("leave_type", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to="leaves.leavetype")),
                ("organization", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="%(class)s_records", to="accounts.organization")),
                ("created_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_created", to=settings.AUTH_USER_MODEL)),
                ("deleted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_deleted", to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="%(class)s_updated", to=settings.AUTH_USER_MODEL)),
            ],
            options={"abstract": False},
        ),
    ]
