from django.contrib import admin
from .models import Grade


@admin.register(Grade)
class GradeAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'term', 'academic_year', 'ca1', 'ca2', 'assignment', 'exam', 'total', 'grade', 'results_status')
    search_fields = ('student__first_name', 'student__last_name', 'subject__name')
    list_filter = ('results_status', 'term', 'academic_year', 'school', 'subject')
