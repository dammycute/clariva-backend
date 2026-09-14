from django.contrib import admin
from .models import Subject, StudentSubject, Exam, Question, TimeTable, TimeSlot, ReportCard, ExamSession


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'school', 'year_group', 'teacher', 'is_core', 'grading_mode')
    search_fields = ('name', 'code')
    list_filter = ('school', 'year_group', 'is_core', 'grading_mode')


@admin.register(StudentSubject)
class StudentSubjectAdmin(admin.ModelAdmin):
    list_display = ('student', 'subject', 'school', 'academic_year')
    search_fields = ('student__first_name', 'student__last_name', 'subject__name')
    list_filter = ('school', 'academic_year')


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = ('title', 'subject', 'school', 'class_group', 'component', 'status', 'start_time', 'end_time', 'duration_mins')
    search_fields = ('title', 'subject__name')
    list_filter = ('status', 'component', 'school', 'term', 'academic_year')


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = ('body', 'exam', 'question_type', 'difficulty', 'mark', 'order')
    search_fields = ('body', 'topic')
    list_filter = ('question_type', 'difficulty', 'school')


@admin.register(TimeTable)
class TimeTableAdmin(admin.ModelAdmin):
    list_display = ('class_group', 'term', 'academic_year', 'is_published', 'period_count')
    search_fields = ('class_group__name',)
    list_filter = ('is_published', 'school', 'term', 'academic_year')


@admin.register(TimeSlot)
class TimeSlotAdmin(admin.ModelAdmin):
    list_display = ('timetable', 'day', 'period', 'subject', 'teacher', 'room', 'start_time', 'end_time')
    search_fields = ('room',)
    list_filter = ('day', 'subject')


@admin.register(ReportCard)
class ReportCardAdmin(admin.ModelAdmin):
    list_display = ('student', 'term', 'academic_year', 'average', 'class_rank', 'is_released')
    search_fields = ('student__first_name', 'student__last_name')
    list_filter = ('is_released', 'school', 'term', 'academic_year')


@admin.register(ExamSession)
class ExamSessionAdmin(admin.ModelAdmin):
    list_display = ('exam', 'student', 'score', 'total_marks', 'passed', 'tab_switches', 'late_submission', 'status')
    search_fields = ('student__first_name', 'student__last_name', 'session_code')
    list_filter = ('status', 'passed', 'late_submission', 'school')
