from django.db import models
from apps.base.models import BaseUUIDModel

class Class(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    year_group = models.CharField(max_length=20, null=True, blank=True)
    arm = models.CharField(max_length=10, null=True, blank=True)
    form_teacher = models.ForeignKey('staff.Staff', on_delete=models.SET_NULL, null=True, blank=True)
    academic_year = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ('year_group', 'arm')
        verbose_name_plural = 'classes'
        constraints = [
            models.UniqueConstraint(fields=['school', 'name'], name='unique_class_per_school'),
        ]
