from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Announcement


def visible_announcements_for(user):
    now = timezone.now()
    audience_filter = Q(audience='ALL')
    if user.is_staff or user.is_superuser:
        audience_filter |= Q(audience='STAFF')
    else:
        audience_filter |= Q(audience='EMPLOYEES')

    return Announcement.objects.filter(
        audience_filter,
        organization=user.organization,
        is_active=True,
        publish_at__lte=now,
    ).filter(
        Q(expires_at__isnull=True) | Q(expires_at__gte=now)
    )


@login_required
def announcement_list(request):
    announcements = visible_announcements_for(request.user)
    category = request.GET.get('category', '')
    if category:
        announcements = announcements.filter(category=category)

    return render(request, 'announcements/list.html', {
        'announcements': announcements,
        'category_choices': Announcement.CATEGORY_CHOICES,
        'selected_category': category,
    })


@login_required
def announcement_detail(request, announcement_id):
    announcement = get_object_or_404(
        visible_announcements_for(request.user),
        id=announcement_id,
    )
    return render(request, 'announcements/detail.html', {'announcement': announcement})


@login_required
def manage_announcements(request, announcement_id=None):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('announcements:list')

    edit_announcement = None
    if announcement_id:
        edit_announcement = get_object_or_404(
            Announcement,
            id=announcement_id,
            organization=request.user.organization,
        )

    if request.method == 'POST':
        title = request.POST.get('title', '').strip()
        category = request.POST.get('category', 'COMPANY_NEWS')
        audience = request.POST.get('audience', 'ALL')
        department = request.POST.get('department', '').strip() or 'HR Department'
        summary = request.POST.get('summary', '').strip()
        body = request.POST.get('body', '').strip()
        publish_at = _parse_local_datetime(request.POST.get('publish_at')) or timezone.now()
        expires_at = _parse_local_datetime(request.POST.get('expires_at'))
        is_pinned = 'is_pinned' in request.POST
        is_active = 'is_active' in request.POST

        if not title or not body:
            messages.error(request, "Title and announcement body are required.")
            return redirect('announcements:edit' if edit_announcement else 'announcements:manage', announcement_id=announcement_id) if edit_announcement else redirect('announcements:manage')

        announcement = edit_announcement or Announcement(
            organization=request.user.organization,
            created_by=request.user,
        )
        announcement.title = title
        announcement.category = category
        announcement.audience = audience
        announcement.department = department
        announcement.summary = summary
        announcement.body = body
        announcement.publish_at = publish_at
        announcement.expires_at = expires_at
        announcement.is_pinned = is_pinned
        announcement.is_active = is_active
        announcement.updated_by = request.user
        announcement.save()

        messages.success(request, "Announcement saved successfully.")
        return redirect('announcements:manage')

    announcements = Announcement.objects.filter(
        organization=request.user.organization,
    ).order_by('-is_pinned', '-publish_at')

    return render(request, 'announcements/manage.html', {
        'announcements': announcements,
        'edit_announcement': edit_announcement,
        'category_choices': Announcement.CATEGORY_CHOICES,
        'audience_choices': Announcement.AUDIENCE_CHOICES,
        'now': timezone.now(),
    })


@login_required
def delete_announcement(request, announcement_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('announcements:list')

    announcement = get_object_or_404(
        Announcement,
        id=announcement_id,
        organization=request.user.organization,
    )
    announcement.is_deleted = True
    announcement.is_active = False
    announcement.deleted_by = request.user
    announcement.deleted_at = timezone.now()
    announcement.save()
    messages.success(request, "Announcement deleted successfully.")
    return redirect('announcements:manage')


@login_required
def toggle_announcement(request, announcement_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "Access denied.")
        return redirect('announcements:list')

    announcement = get_object_or_404(
        Announcement,
        id=announcement_id,
        organization=request.user.organization,
    )
    announcement.is_active = not announcement.is_active
    announcement.updated_by = request.user
    announcement.save()
    messages.success(request, "Announcement status updated.")
    return redirect('announcements:manage')


def _parse_local_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if not parsed:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed

