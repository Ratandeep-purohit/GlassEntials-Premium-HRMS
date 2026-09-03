from django.contrib import admin

from .models import Announcement, AnnouncementImage


class AnnouncementImageInline(admin.TabularInline):
    model = AnnouncementImage
    extra = 0
    readonly_fields = ('original_filename', 'created_at')


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'organization', 'category', 'audience', 'is_pinned', 'is_active', 'publish_at')
    list_filter = ('category', 'audience', 'is_pinned', 'is_active', 'organization')
    search_fields = ('title', 'summary', 'body', 'department')
    date_hierarchy = 'publish_at'
    inlines = [AnnouncementImageInline]


@admin.register(AnnouncementImage)
class AnnouncementImageAdmin(admin.ModelAdmin):
    list_display = ('announcement', 'original_filename', 'display_order', 'created_at')
    list_filter = ('announcement__organization',)
    raw_id_fields = ('announcement',)
