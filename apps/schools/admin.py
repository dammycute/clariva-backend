from django.contrib import admin
from .models import School, GradingConfig


@admin.register(School)
class SchoolAdmin(admin.ModelAdmin):
    list_display = ('name', 'subdomain', 'school_type', 'state', 'lga', 'current_term', 'current_academic_year', 'plan', 'status')
    search_fields = ('name', 'subdomain', 'proprietor_name')
    list_filter = ('plan', 'status', 'school_type', 'state')


@admin.register(GradingConfig)
class GradingConfigAdmin(admin.ModelAdmin):
    list_display = ('school',)
    search_fields = ('school__name',)
    list_filter = ('school',)
