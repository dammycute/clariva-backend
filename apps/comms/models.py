from django.db import models
from django.conf import settings
from apps.base.models import BaseUUIDModel

class Announcement(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    body = models.TextField()
    audience = models.CharField(max_length=100, null=True, blank=True)
    created_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title


class Notification(BaseUUIDModel):
    NOTIF_TYPES = [
        ('attendance', 'Attendance'),
        ('exam', 'Exam'),
        ('fee', 'Fee'),
        ('announcement', 'Announcement'),
        ('grade', 'Grade'),
        ('system', 'System'),
    ]

    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    notif_type = models.CharField(max_length=20, choices=NOTIF_TYPES)
    title = models.CharField(max_length=255)
    message = models.TextField()
    read = models.BooleanField(default=False)
    link = models.CharField(max_length=500, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'[{self.notif_type}] {self.title}'
