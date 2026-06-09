from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from apps.base.models import BaseUUIDModel

DEFAULT_GRADE_BOUNDARIES = [
    {"name": "A1", "min_pct": 75}, {"name": "B2", "min_pct": 70},
    {"name": "B3", "min_pct": 65}, {"name": "C4", "min_pct": 60},
    {"name": "C5", "min_pct": 55}, {"name": "C6", "min_pct": 50},
    {"name": "D7", "min_pct": 45}, {"name": "E8", "min_pct": 40},
    {"name": "F9", "min_pct": 0},
]

PREDEFINED_COMPONENTS = [
    {"key": "ca1", "default_label": "CA 1", "default_max": 30},
    {"key": "ca2", "default_label": "CA 2", "default_max": 30},
    {"key": "assignment", "default_label": "Assignment", "default_max": 40},
    {"key": "exam", "default_label": "Exam", "default_max": 100},
]

DEFAULT_COMPONENTS = [
    {"key": "ca1", "label": "CA 1", "max": 30, "enabled": True},
    {"key": "ca2", "label": "CA 2", "max": 30, "enabled": True},
    {"key": "assignment", "label": "Assignment", "max": 40, "enabled": True},
    {"key": "exam", "label": "Exam", "max": 100, "enabled": True},
]


class GradingConfig(BaseUUIDModel):
    school = models.OneToOneField('schools.School', on_delete=models.CASCADE, related_name='grading_config')
    components = models.JSONField(default=list, help_text='[{"key":"ca1","label":"CA 1","max":30,"enabled":true},...]')
    grade_boundaries = models.JSONField(default=list, help_text='[{"name":"A1","min_pct":75},...]')

    @property
    def total_possible(self):
        return sum(c['max'] for c in self.components if c.get('enabled', True))

    @property
    def total_ca(self):
        return sum(c['max'] for c in self.components
                    if c.get('enabled', True) and c.get('key') != 'exam')

    def get_grade(self, score: float) -> str:
        if not self.grade_boundaries or self.total_possible == 0:
            return '—'
        pct = (score / self.total_possible) * 100
        for g in sorted(self.grade_boundaries, key=lambda x: x['min_pct'], reverse=True):
            if pct >= g['min_pct']:
                return g['name']
        return self.grade_boundaries[-1]['name'] if self.grade_boundaries else '—'

    class Meta:
        verbose_name = 'Grading Configuration'

    def __str__(self):
        return f'{self.school.name} Grading'


class School(BaseUUIDModel):
    name = models.CharField(max_length=255)
    subdomain = models.CharField(max_length=100, unique=True)
    logo_url = models.URLField(null=True, blank=True)
    accent_color = models.CharField(max_length=7, default='#1A7A4A')
    address = models.TextField(null=True, blank=True)
    lga = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    school_type = models.CharField(max_length=100, null=True, blank=True)
    proprietor_name = models.CharField(max_length=255, null=True, blank=True)
    proprietor_phone = models.CharField(max_length=20, null=True, blank=True)
    current_term = models.CharField(max_length=50, default='1st Term')
    current_academic_year = models.CharField(max_length=20, default='2025/2026')
    plan = models.CharField(max_length=50, default='trial')
    status = models.CharField(max_length=20, default='active')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
