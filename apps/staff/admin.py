from django.contrib import admin
from .models import TeacherProfile, StaffProfile


@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'school', 'qualification', 'date_joined', 'status')
    search_fields = ('user__first_name', 'user__last_name', 'qualification')
    list_filter = ('status', 'school', 'date_joined')


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'school', 'designation', 'qualification', 'date_joined', 'status')
    search_fields = ('user__first_name', 'user__last_name', 'designation', 'qualification')
    list_filter = ('status', 'school', 'date_joined')
