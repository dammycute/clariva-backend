from django.db import models
from apps.base.models import BaseUUIDModel


class Staff(BaseUUIDModel):
    user = models.OneToOneField('accounts.User', on_delete=models.CASCADE, related_name='staff_profile')
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    role = models.CharField(max_length=100)
    qualification = models.CharField(max_length=100, null=True, blank=True)
    subjects = models.JSONField(null=True, blank=True)
    date_joined = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.get_full_name() or str(self.user)
