from django.contrib import admin
from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'model_name', 'object_repr', 'ip_address', 'school', 'created_at')
    search_fields = ('user__first_name', 'user__last_name', 'action', 'model_name', 'object_repr', 'object_id')
    list_filter = ('action', 'model_name', 'school', 'created_at')
    readonly_fields = ('user', 'action', 'model_name', 'object_id', 'object_repr', 'changes', 'ip_address', 'school', 'created_at')
