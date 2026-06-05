from datetime import time
from django.db import models
from apps.base.models import BaseUUIDModel

class Subject(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, null=True, blank=True)
    year_group = models.CharField(max_length=20, null=True, blank=True, help_text='e.g. SS1 — available to all classes in this year group')
    teacher = models.ForeignKey('staff.Staff', on_delete=models.SET_NULL, null=True, blank=True)
    is_core = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['school', 'name', 'year_group']

    def __str__(self):
        return f'{self.name} ({self.year_group or "All"})'

class StudentSubject(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    academic_year = models.CharField(max_length=20, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['student', 'subject', 'academic_year']

    def __str__(self):
        return f'{self.student.full_name} — {self.subject.name}'

class Exam(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    title = models.CharField(max_length=255)
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    class_group = models.ForeignKey('classes.Class', on_delete=models.SET_NULL, null=True, blank=True)
    duration_mins = models.IntegerField()
    pass_mark = models.IntegerField(default=40)
    question_count = models.IntegerField(null=True, blank=True)
    instructions = models.TextField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, default='draft')
    shuffle_questions = models.BooleanField(default=False)
    shuffle_options = models.BooleanField(default=False)
    time_limit_enforced = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

class Question(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.SET_NULL, null=True, blank=True)
    body = models.TextField()
    image_url = models.URLField(null=True, blank=True)
    question_type = models.CharField(max_length=20, choices=[
        ('mcq', 'Multiple Choice'), ('true_false', 'True/False'), ('short_answer', 'Short Answer')
    ])
    options = models.JSONField(null=True, blank=True)
    correct_answer = models.TextField()
    topic = models.CharField(max_length=255, null=True, blank=True)
    difficulty = models.CharField(max_length=10, default='medium')
    mark = models.IntegerField(default=1)
    order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

class TimeTable(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    class_group = models.ForeignKey('classes.Class', on_delete=models.CASCADE)
    term = models.CharField(max_length=50)
    academic_year = models.CharField(max_length=20)
    is_published = models.BooleanField(default=False)
    start_time = models.TimeField(default=time(8, 0), help_text='First period start time')
    period_duration = models.IntegerField(default=40, help_text='Minutes per period')
    period_count = models.IntegerField(default=8, help_text='Number of periods per day')
    short_break_after_period = models.IntegerField(default=0, help_text='Period after which short break occurs (0 = none)')
    short_break_duration = models.IntegerField(default=10, help_text='Short break minutes')
    long_break_after_period = models.IntegerField(default=0, help_text='Period after which long break occurs (0 = none)')
    long_break_duration = models.IntegerField(default=0, help_text='Long break minutes')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['school', 'class_group', 'term', 'academic_year']

    def _total_break_before(self, period: int) -> int:
        mins = 0
        if self.short_break_after_period and period > self.short_break_after_period:
            mins += self.short_break_duration
        if self.long_break_after_period and period > self.long_break_after_period:
            mins += self.long_break_duration
        return mins

    def period_start_time(self, period: int) -> str:
        from datetime import datetime, timedelta
        start = datetime.combine(datetime.today(), self.start_time)
        offset = (period - 1) * self.period_duration + self._total_break_before(period)
        return (start + timedelta(minutes=offset)).strftime('%H:%M:%S')

    def period_end_time(self, period: int) -> str:
        from datetime import datetime, timedelta
        start = datetime.combine(datetime.today(), self.start_time)
        offset = (period - 1) * self.period_duration + self._total_break_before(period)
        period_start = start + timedelta(minutes=offset)
        return (period_start + timedelta(minutes=self.period_duration)).strftime('%H:%M:%S')

    def __str__(self):
        return f'{self.class_group.name} — {self.term} {self.academic_year}'

DAY_CHOICES = [
    (0, 'Monday'), (1, 'Tuesday'), (2, 'Wednesday'),
    (3, 'Thursday'), (4, 'Friday'),
]

class TimeSlot(BaseUUIDModel):
    timetable = models.ForeignKey(TimeTable, on_delete=models.CASCADE, related_name='slots')
    day = models.IntegerField(choices=DAY_CHOICES)
    period = models.IntegerField(help_text='Period number (1-based)')
    start_time = models.TimeField()
    end_time = models.TimeField()
    subject = models.ForeignKey(Subject, on_delete=models.SET_NULL, null=True, blank=True)
    teacher = models.ForeignKey('staff.Staff', on_delete=models.SET_NULL, null=True, blank=True)
    room = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        unique_together = ['timetable', 'day', 'period']
        ordering = ['day', 'period']

    def __str__(self):
        return f'{self.get_day_display()} P{self.period} — {self.subject.name if self.subject else "Free"}'


class ReportCard(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    term = models.CharField(max_length=50)
    academic_year = models.CharField(max_length=20)
    grades = models.JSONField(help_text='Snapshot of all subject grades for this term')
    total_score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    total_possible = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    average = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    class_rank = models.IntegerField(null=True, blank=True)
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['student', 'term', 'academic_year']

    def __str__(self):
        return f'{self.student.full_name} — {self.term} {self.academic_year}'


class ExamSession(BaseUUIDModel):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE)
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    session_code = models.CharField(max_length=20, null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    score = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    total_marks = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    passed = models.BooleanField(null=True)
    answers = models.JSONField(null=True, blank=True)
    tab_switches = models.IntegerField(default=0)
    device_info = models.JSONField(null=True, blank=True)
    question_order = models.JSONField(null=True, blank=True)
    late_submission = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default='pending')

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['exam', 'student'], name='unique_exam_student'),
        ]
