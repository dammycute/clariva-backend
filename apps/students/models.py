from django.db import models
from fernet_fields import EncryptedCharField, EncryptedEmailField

from apps.base.models import BaseUUIDModel


class StudentProfile(BaseUUIDModel):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='student_profile'
    )
    school = models.ForeignKey(
        'schools.School',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        help_text='Denormalized from user.school for direct querying',
    )
    admission_no = models.CharField(max_length=50, unique=True, null=True, blank=True)
    class_group = models.ForeignKey(
        'classes.Class',
        on_delete=models.SET_NULL,
        null=True, blank=True
    )
    guardian_name = EncryptedCharField(max_length=255, null=True, blank=True)
    guardian_phone = EncryptedCharField(max_length=20, null=True, blank=True)
    guardian_email = EncryptedEmailField(null=True, blank=True)
    student_status = models.CharField(max_length=20, default='active')
    academic_year = models.CharField(max_length=20, null=True, blank=True)

    def __str__(self):
        return f'Profile — {self.user.get_full_name()}'
