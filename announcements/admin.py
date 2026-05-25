from django.contrib import admin

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'category', 'audience', 'is_pinned', 'is_active', 'publish_at')
    list_filter = ('category', 'audience', 'is_pinned', 'is_active', 'organization')
    search_fields = ('title', 'summary', 'body', 'department')
    date_hierarchy = 'publish_at'

