from django.db import models
from django.db.models.signals import post_save
from apps.base.models import BaseUUIDModel
from django.dispatch import receiver
import secrets
import string


def generate_access_code():
    chars = string.ascii_uppercase + string.digits
    return 'CLR-' + ''.join(secrets.choice(chars) for _ in range(8))


class StudentAccessCode(BaseUUIDModel):
    student = models.OneToOneField('Student', on_delete=models.CASCADE, related_name='access_code_link')
    code = models.CharField(max_length=12, unique=True, default=generate_access_code)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.code} — {self.student.full_name}'


class Student(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    admission_no = models.CharField(max_length=50, unique=True)
    full_name = models.CharField(max_length=255)
    dob = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=10, null=True, blank=True)
    lga_of_origin = models.CharField(max_length=100, null=True, blank=True)
    state_of_origin = models.CharField(max_length=100, null=True, blank=True)
    photo_url = models.URLField(null=True, blank=True)
    class_group = models.ForeignKey('classes.Class', on_delete=models.SET_NULL, null=True, blank=True)
    guardian_name = models.CharField(max_length=255, null=True, blank=True)
    guardian_phone = models.CharField(max_length=20, null=True, blank=True)
    guardian_email = models.EmailField(null=True, blank=True)
    status = models.CharField(max_length=20, default='active')
    academic_year = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.full_name} ({self.admission_no})'


@receiver(post_save, sender=Student)
def create_student_access_code(sender, instance, created, **kwargs):
    if created:
        StudentAccessCode.objects.get_or_create(student=instance)
