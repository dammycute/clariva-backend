from django.db import models

class Grade(models.Model):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    subject = models.ForeignKey('exams.Subject', on_delete=models.CASCADE)
    term = models.CharField(max_length=20)
    academic_year = models.CharField(max_length=20)
    ca1 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    ca2 = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    assignment = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    exam = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    total = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    grade = models.CharField(max_length=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['student', 'subject', 'term', 'academic_year']

    def __str__(self):
        return f'{self.student.full_name} - {self.subject.name} - {self.term}'
