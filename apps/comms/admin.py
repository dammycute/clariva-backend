from django.contrib import admin
from .models import Announcement, Notification


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'school', 'audience', 'created_by', 'published_at')
    search_fields = ('title', 'body')
    list_filter = ('school', 'published_at')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('recipient', 'notif_type', 'title', 'read', 'created_at')
    search_fields = ('title', 'message', 'recipient__first_name', 'recipient__last_name')
    list_filter = ('notif_type', 'read', 'school')
