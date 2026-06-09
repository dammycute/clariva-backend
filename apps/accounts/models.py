import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models

from apps.base.models import BaseUUIDModel

ROLE_CHOICES = [
    ('super_admin', 'Super Admin'),
    ('school_admin', 'School Admin'),
    ('principal', 'Principal'),
    ('teacher', 'Teacher'),
    ('bursary', 'Bursary'),
    ('student', 'Student'),
    ('parent', 'Parent'),
]


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='school_admin')
    avatar_url = models.URLField(null=True, blank=True)
    photo_url = models.URLField(null=True, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    lga_of_origin = models.CharField(max_length=100, null=True, blank=True)
    state_of_origin = models.CharField(max_length=100, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    last_login = models.DateTimeField(null=True, blank=True)

    # Student-specific fields
    admission_no = models.CharField(max_length=50, null=True, blank=True, unique=True)
    class_group = models.ForeignKey('classes.Class', on_delete=models.SET_NULL, null=True, blank=True)
    guardian_name = models.CharField(max_length=255, null=True, blank=True)
    guardian_phone = models.CharField(max_length=20, null=True, blank=True)
    guardian_email = models.EmailField(null=True, blank=True)
    student_status = models.CharField(max_length=20, default='active')
    academic_year = models.CharField(max_length=20, null=True, blank=True)

    def __str__(self):
        name = self.get_full_name() or self.username or self.email or 'Unnamed'
        return f'{name} ({self.role})'


class StudentAccessCode(BaseUUIDModel):
    student = models.OneToOneField(User, on_delete=models.CASCADE, related_name='access_code_link')
    code = models.CharField(max_length=12, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.code} — {self.student.get_full_name()}'
