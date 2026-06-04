from django.db import models
from django.contrib.auth.hashers import make_password, check_password
from apps.base.models import BaseUUIDModel


class GuardianAccount(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    phone = models.CharField(max_length=20)
    pin = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['school', 'phone']

    def set_pin(self, raw_pin):
        self.pin = make_password(raw_pin)

    def check_pin(self, raw_pin):
        return check_password(raw_pin, self.pin)

    def __str__(self):
        return f'{self.phone} ({self.school.name})'


class GuardianStudent(BaseUUIDModel):
    guardian = models.ForeignKey(GuardianAccount, on_delete=models.CASCADE, related_name='links')
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['guardian', 'student']

    def __str__(self):
        return f'{self.guardian.phone} → {self.student.full_name}'
