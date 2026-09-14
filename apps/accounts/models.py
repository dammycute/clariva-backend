import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from fernet_fields import EncryptedCharField, EncryptedDateField

from apps.base.models import BaseUUIDModel
from apps.base.encryption import hash_value

ROLE_CHOICES = [
    ('super_admin', 'Super Admin'),
    ('school_admin', 'School Admin'),
    ('admin_officer', 'Admin Officer'),
    ('principal', 'Principal'),
    ('teacher', 'Teacher'),
    ('bursary', 'Bursary'),
    ('student', 'Student'),
    ('parent', 'Parent'),
]


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, null=True, blank=True)
    phone = EncryptedCharField(max_length=20, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='school_admin')
    avatar_url = models.URLField(null=True, blank=True)
    photo_url = models.URLField(null=True, blank=True)
    date_of_birth = EncryptedDateField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    lga_of_origin = EncryptedCharField(max_length=100, null=True, blank=True)
    state_of_origin = EncryptedCharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        name = self.get_full_name() or self.username or self.email or 'Unnamed'
        return f'{name} ({self.role})'


class StudentAccessCode(BaseUUIDModel):
    student = models.OneToOneField(User, on_delete=models.CASCADE, related_name='access_code_link')
    code = models.CharField(max_length=12, unique=True)
    code_hash = models.CharField(max_length=64, unique=True, db_index=True, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.code and not self.code_hash:
            self.code_hash = hash_value(self.code)
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} — {self.student.get_full_name()}'
