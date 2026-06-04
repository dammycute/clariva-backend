from django.db import models
from apps.base.models import BaseUUIDModel

class Staff(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    full_name = models.CharField(max_length=255)
    role = models.CharField(max_length=100)
    qualification = models.CharField(max_length=100, null=True, blank=True)
    subjects = models.JSONField(null=True, blank=True)
    phone = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(null=True, blank=True)
    date_joined = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.full_name
