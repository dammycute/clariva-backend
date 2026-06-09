from django.db import models
from apps.base.models import BaseUUIDModel

class Attendance(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    student = models.ForeignKey('accounts.User', on_delete=models.CASCADE, related_name='attendance_records')
    class_group = models.ForeignKey('classes.Class', on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    status = models.CharField(max_length=10, choices=[('present', 'Present'), ('absent', 'Absent'), ('late', 'Late')])
    marked_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='marked_attendance')
    marked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.student.get_full_name()} - {self.date} - {self.status}'
