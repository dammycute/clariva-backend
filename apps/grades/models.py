from django.db import models
from apps.base.models import BaseUUIDModel

class Grade(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    student = models.ForeignKey('accounts.User', on_delete=models.CASCADE)
    subject = models.ForeignKey('exams.Subject', on_delete=models.CASCADE)
    term = models.CharField(max_length=20)
    academic_year = models.CharField(max_length=20)
    scores = models.JSONField(default=dict, blank=True)
    total = models.IntegerField(null=True, blank=True)
    grade = models.CharField(max_length=2, null=True, blank=True)
    results_status = models.CharField(max_length=20, default='draft', choices=[
        ('draft', 'Draft'), ('submitted', 'Submitted'), ('approved', 'Approved'), ('rejected', 'Rejected'),
    ])
    submitted_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='submitted_grades')
    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_grades')
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_note = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['student', 'subject', 'term', 'academic_year']

    def __str__(self):
        return f'{self.student.get_full_name()} - {self.subject.name} - {self.term}'
