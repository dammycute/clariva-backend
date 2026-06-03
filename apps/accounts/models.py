from django.contrib.auth.models import AbstractUser
from django.db import models

ROLE_CHOICES = [
    ('super_admin', 'Super Admin'),
    ('school_admin', 'School Admin'),
    ('principal', 'Principal'),
    ('teacher', 'Teacher'),
    ('student', 'Student'),
    ('parent', 'Parent'),
]

class User(AbstractUser):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='school_admin')
    avatar_url = models.URLField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.get_full_name() or self.username} ({self.role})'
