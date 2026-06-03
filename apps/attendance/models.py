from django.db import models

class Attendance(models.Model):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    class_group = models.ForeignKey('classes.Class', on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    status = models.CharField(max_length=10, choices=[('present', 'Present'), ('absent', 'Absent'), ('late', 'Late')])
    marked_by = models.ForeignKey('staff.Staff', on_delete=models.SET_NULL, null=True, blank=True)
    marked_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.student.full_name} - {self.date} - {self.status}'
