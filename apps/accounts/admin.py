from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, StudentAccessCode


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'school', 'is_active')
    list_filter = ('role', 'is_active', 'school', 'gender')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'phone')
    fieldsets = BaseUserAdmin.fieldsets + (
        ('Clariva', {'fields': ('school', 'role', 'phone', 'avatar_url', 'photo_url', 'date_of_birth', 'gender', 'lga_of_origin', 'state_of_origin')}),
    )


@admin.register(StudentAccessCode)
class StudentAccessCodeAdmin(admin.ModelAdmin):
    list_display = ('code', 'student', 'created_at')
    search_fields = ('code', 'student__first_name', 'student__last_name')
    list_filter = ('created_at',)
