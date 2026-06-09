from django.db import models
from apps.base.models import BaseUUIDModel


class GuardianStudent(BaseUUIDModel):
    guardian = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='ward_links')
    student = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='guardian_links')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['guardian', 'student']

    def __str__(self):
        return f'{self.guardian.get_full_name()} → {self.student.get_full_name()}'
