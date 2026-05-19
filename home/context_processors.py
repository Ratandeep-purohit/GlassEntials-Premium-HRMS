from accounts.models import CustomUser
from attendance.models import AttendanceCorrection, OvertimeRequest
from leaves.models import LeaveRequest

def global_notifications(request):
    notifications = []
    
    if request.user.is_authenticated:
        from home.models import Notification
        # Fetch actual Notification objects for any user
        user_alerts = Notification.objects.filter(user=request.user, is_read=False)
        for alert in user_alerts:
            notifications.append({
                'title': alert.title,
                'message': alert.message,
                'type': alert.notification_type.lower(),
                'link': alert.link,
                'timestamp': alert.created_at,
            })

    if request.user.is_authenticated and request.user.is_staff:
        organization = request.user.organization
        
        # 1. New User Approvals
        pending_users = CustomUser.objects.filter(organization=organization, is_approved=False, is_active=True)
        for u in pending_users:
            notifications.append({
                'title': f"New User: {u.username}",
                'message': "Needs approval to join.",
                'type': 'user_approval',
                'link': '/accounts/approve_users/',
                'timestamp': u.date_joined,
            })
            
        # 2. Leave Requests
        pending_leaves = LeaveRequest.objects.filter(organization=organization, status='PENDING')
        for l in pending_leaves:
            notifications.append({
                'title': f"Leave Request: {l.employee.first_name}",
                'message': f"Requested {l.total_days} days off.",
                'type': 'leave',
                'link': '/leaves/pending/',
                'timestamp': l.created_at,
            })
            
        # 3. Attendance Corrections
        pending_corrections = AttendanceCorrection.objects.filter(employee__organization=organization, status='PENDING')
        for c in pending_corrections:
            notifications.append({
                'title': f"Attendance: {c.employee.first_name}",
                'message': f"Correction for {c.attendance.date}.",
                'type': 'correction',
                'link': '/attendance/manage-corrections/',
                'timestamp': c.created_at,
            })
            
        # 4. Overtime Requests
        pending_overtimes = OvertimeRequest.objects.filter(employee__organization=organization, status='PENDING')
        for o in pending_overtimes:
            notifications.append({
                'title': f"Overtime: {o.employee.first_name}",
                'message': f"Requested {o.hours_requested}h overtime.",
                'type': 'overtime',
                'link': '/attendance/overtime/',
                'timestamp': o.created_at,
            })
            
    # Find current employee if logged in
    current_employee = None
    if request.user.is_authenticated:
        try:
            from employees.models import Employee
            current_employee = Employee.objects.filter(email=request.user.email).first()
        except Exception:
            pass

    # Sort notifications by timestamp descending
    if notifications:
        notifications.sort(key=lambda x: x['timestamp'], reverse=True)
        
    return {
        'global_notifications': notifications,
        'global_notifications_count': len(notifications),
        'current_employee': current_employee
    }

