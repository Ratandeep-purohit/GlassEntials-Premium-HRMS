from django.contrib import admin
from .models import AssetCategory, Asset, AssetAssignment, AssetRequest

@admin.register(AssetCategory)
class AssetCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'icon', 'organization')

@admin.register(Asset)
class AssetAdmin(admin.ModelAdmin):
    list_display = ('asset_code', 'name', 'category', 'status', 'condition', 'organization')
    list_filter = ('status', 'condition', 'category')

@admin.register(AssetAssignment)
class AssetAssignmentAdmin(admin.ModelAdmin):
    list_display = ('asset', 'employee', 'assigned_date', 'status')

@admin.register(AssetRequest)
class AssetRequestAdmin(admin.ModelAdmin):
    list_display = ('employee', 'category', 'priority', 'status')
