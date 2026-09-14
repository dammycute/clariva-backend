from django.contrib import admin
from .models import StudentProfile


@admin.register(StudentProfile)
class StudentProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'admission_no', 'class_group', 'student_status', 'academic_year', 'guardian_name')
    search_fields = ('user__first_name', 'user__last_name', 'admission_no', 'guardian_name', 'guardian_phone')
    list_filter = ('student_status', 'academic_year', 'class_group')
