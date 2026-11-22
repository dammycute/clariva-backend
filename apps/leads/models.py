from django.db import models
from fernet_fields import EncryptedCharField

from apps.base.models import BaseUUIDModel


class DemoRequest(BaseUUIDModel):
    """Someone on the landing page asking for a demo. Contact details are encrypted like other personal data."""
    ROLES = [('proprietor', 'Proprietor or owner'), ('principal', 'Principal or head teacher'),
             ('admin', 'School administrator'), ('other', 'Other')]

    name = models.CharField(max_length=200)
    school_name = models.CharField(max_length=200)
    role = models.CharField(max_length=20, choices=ROLES, default='other')
    phone = EncryptedCharField(max_length=30)
    email = EncryptedCharField(max_length=254, blank=True, default='')
    students = models.PositiveIntegerField(null=True, blank=True)
    message = models.TextField(blank=True, default='')
    emailed = models.BooleanField(default=False, help_text='The notification email was sent.')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.school_name} ({self.name})'
