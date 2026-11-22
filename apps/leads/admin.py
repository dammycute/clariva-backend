from django.contrib import admin

from .models import DemoRequest


@admin.register(DemoRequest)
class DemoRequestAdmin(admin.ModelAdmin):
    list_display = ('school_name', 'name', 'role', 'students', 'created_at', 'emailed')
    list_filter = ('role', 'emailed')
    search_fields = ('school_name', 'name')
