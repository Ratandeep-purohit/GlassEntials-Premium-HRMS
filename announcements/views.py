import os

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from .models import Announcement, AnnouncementImage

# ── Constants ────────────────────────────────────────────────────────────────
MAX_IMAGES_PER_ANNOUNCEMENT = 10
MAX_IMAGE_SIZE_MB = 8
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp', 'gif'}

# Magic bytes for quick header validation
_MAGIC = {
    b'\xff\xd8\xff': 'jpeg',
    b'\x89PNG': 'png',
    b'GIF87a': 'gif',
    b'GIF89a': 'gif',
    b'RIFF': 'webp',  # RIFF....WEBP — checked further below
}


def _sniff_image_type(header):
    """Return image type string or None based on file magic bytes."""
    for magic, kind in _MAGIC.items():
        if header[:len(magic)] == magic:
            if kind == 'webp' and header[8:12] != b'WEBP':
                return None
            return kind
    return None


def _validate_image_file(f):
    """Returns an error string if the file is invalid, or None if OK."""
    ext = f.name.rsplit('.', 1)[-1].lower() if '.' in f.name else ''
    if ext not in ALLOWED_EXTENSIONS:
        return f"'{f.name}' is not a supported image format (JPEG, PNG, WEBP, GIF only)."
    if f.size > MAX_IMAGE_SIZE_MB * 1024 * 1024:
        return f"'{f.name}' exceeds the {MAX_IMAGE_SIZE_MB} MB size limit."
    header = f.read(16)
    f.seek(0)
    detected = _sniff_image_type(header)
    if detected is not None:
        ext_map = {'jpg': 'jpeg', 'jpeg': 'jpeg', 'png': 'png', 'webp': 'webp', 'gif': 'gif'}
        if detected != ext_map.get(ext, ext):
            return f"'{f.name}' file contents do not match its extension."
    return None


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
    ).prefetch_related(
        Prefetch('images', queryset=AnnouncementImage.objects.order_by('display_order', 'created_at'))
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
            return (
                redirect('announcements:edit', announcement_id=announcement_id)
                if edit_announcement else redirect('announcements:manage')
            )

        # Validate uploaded images
        uploaded_images = request.FILES.getlist('images')
        existing_image_count = edit_announcement.images.count() if edit_announcement else 0
        # Handle deletions requested alongside the save
        delete_ids = [
            int(x) for x in request.POST.getlist('delete_image_ids')
            if x.isdigit()
        ]
        effective_existing = existing_image_count - len(delete_ids)
        total_after = effective_existing + len(uploaded_images)
        if total_after > MAX_IMAGES_PER_ANNOUNCEMENT:
            messages.error(
                request,
                f"You can only have up to {MAX_IMAGES_PER_ANNOUNCEMENT} images per announcement. "
                f"Currently {effective_existing} image(s) + {len(uploaded_images)} new = {total_after}."
            )
            return (
                redirect('announcements:edit', announcement_id=announcement_id)
                if edit_announcement else redirect('announcements:manage')
            )

        image_errors = []
        for f in uploaded_images:
            err = _validate_image_file(f)
            if err:
                image_errors.append(err)
        if image_errors:
            for err in image_errors:
                messages.error(request, err)
            return (
                redirect('announcements:edit', announcement_id=announcement_id)
                if edit_announcement else redirect('announcements:manage')
            )

        # Save the announcement
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

        # Delete requested images (verify org ownership via announcement FK)
        if delete_ids and edit_announcement:
            AnnouncementImage.objects.filter(
                id__in=delete_ids,
                announcement__organization=request.user.organization,
            ).delete()

        # Save new images
        for idx, f in enumerate(uploaded_images):
            ann_img = AnnouncementImage(
                announcement=announcement,
                original_filename=f.name,
                display_order=effective_existing + idx,
            )
            ann_img.image = f
            ann_img.save()

        messages.success(request, "Announcement saved successfully.")
        return redirect('announcements:manage')

    announcements = Announcement.objects.filter(
        organization=request.user.organization,
    ).prefetch_related('images').order_by('-is_pinned', '-publish_at')

    return render(request, 'announcements/manage.html', {
        'announcements': announcements,
        'edit_announcement': edit_announcement,
        'category_choices': Announcement.CATEGORY_CHOICES,
        'audience_choices': Announcement.AUDIENCE_CHOICES,
        'now': timezone.now(),
        'max_images': MAX_IMAGES_PER_ANNOUNCEMENT,
        'max_size_mb': MAX_IMAGE_SIZE_MB,
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
    # Soft-delete the announcement; images remain in storage but cascade-orphan is acceptable.
    # (Hard deletion of media files is an operational task, not done inline here.)
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


@login_required
@require_POST
def delete_announcement_image(request, image_id):
    """AJAX endpoint to delete a single image from an announcement."""
    if not (request.user.is_staff or request.user.is_superuser):
        return JsonResponse({'error': 'Access denied.'}, status=403)

    img = get_object_or_404(
        AnnouncementImage,
        id=image_id,
        announcement__organization=request.user.organization,
    )
    img.delete()
    return JsonResponse({'success': True})


def _parse_local_datetime(value):
    if not value:
        return None
    parsed = parse_datetime(value)
    if not parsed:
        return None
    if timezone.is_naive(parsed):
        return timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed
