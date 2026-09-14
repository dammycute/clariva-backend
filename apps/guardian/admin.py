from django.contrib import admin
from .models import GuardianStudent


@admin.register(GuardianStudent)
class GuardianStudentAdmin(admin.ModelAdmin):
    list_display = ('guardian', 'student', 'created_at')
    search_fields = ('guardian__first_name', 'guardian__last_name', 'student__first_name', 'student__last_name')
    list_filter = ('created_at',)
