from django.db import models
from apps.base.models import BaseUUIDModel


class TeacherProfile(BaseUUIDModel):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='teacher_profile'
    )
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    qualification = models.CharField(max_length=100, null=True, blank=True)
    date_joined = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Teacher — {self.user.get_full_name()}'


class StaffProfile(BaseUUIDModel):
    user = models.OneToOneField(
        'accounts.User',
        on_delete=models.CASCADE,
        related_name='staff_profile'
    )
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    designation = models.CharField(max_length=100, null=True, blank=True)
    qualification = models.CharField(max_length=100, null=True, blank=True)
    date_joined = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Staff — {self.user.get_full_name()}'
