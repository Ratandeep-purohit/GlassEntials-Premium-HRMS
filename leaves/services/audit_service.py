from .utils import request_ip
from leaves.models import LeaveAuditLog


class LeaveAuditService:
    @staticmethod
    def record(*, organization, entity, action, user=None, old_value=None, new_value=None, request=None):
        LeaveAuditLog.objects.create(
            organization=organization,
            entity_type=entity.__class__.__name__ if entity else "Unknown",
            entity_id=str(getattr(entity, "pk", "")),
            action=action,
            old_value=old_value or {},
            new_value=new_value or {},
            performed_by=user,
            ip_address=request_ip(request) if request else None,
            user_agent=request.META.get("HTTP_USER_AGENT", "") if request else "",
            created_by=user,
        )
