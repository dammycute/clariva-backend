from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator
from fernet_fields import EncryptedCharField, EncryptedTextField

from apps.base.models import BaseUUIDModel

TERM_CHOICES = [
    ('1st Term', '1st Term'),
    ('2nd Term', '2nd Term'),
    ('3rd Term', '3rd Term'),
]

DEFAULT_GRADE_BOUNDARIES = [
    {"name": "A1", "min_pct": 75}, {"name": "B2", "min_pct": 70},
    {"name": "B3", "min_pct": 65}, {"name": "C4", "min_pct": 60},
    {"name": "C5", "min_pct": 55}, {"name": "C6", "min_pct": 50},
    {"name": "D7", "min_pct": 45}, {"name": "E8", "min_pct": 40},
    {"name": "F9", "min_pct": 0},
]

PREDEFINED_COMPONENTS = [
    {"key": "ca1", "default_label": "CA 1", "default_max": 10},
    {"key": "ca2", "default_label": "CA 2", "default_max": 10},
    {"key": "assignment", "default_label": "Assignment", "default_max": 10},
    {"key": "exam", "default_label": "Exam", "default_max": 70},
]

DEFAULT_COMPONENTS = [
    {"key": "ca1", "label": "CA 1", "max": 10, "enabled": True},
    {"key": "ca2", "label": "CA 2", "max": 10, "enabled": True},
    {"key": "assignment", "label": "Assignment", "max": 10, "enabled": True},
    {"key": "exam", "label": "Exam", "max": 70, "enabled": True},
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
    address = EncryptedTextField(null=True, blank=True)
    lga = models.CharField(max_length=100, null=True, blank=True)
    state = models.CharField(max_length=100, null=True, blank=True)
    school_type = models.CharField(max_length=100, null=True, blank=True)
    proprietor_name = EncryptedCharField(max_length=255, null=True, blank=True)
    proprietor_phone = EncryptedCharField(max_length=20, null=True, blank=True)
    current_term = models.CharField(max_length=50, choices=TERM_CHOICES, default='1st Term')
    current_academic_year = models.CharField(max_length=20, default='2025/2026')
    plan = models.CharField(max_length=50, default='trial')
    # A student can be signed in on one device at a time.
    single_device_students = models.BooleanField(default=True)
    status = models.CharField(max_length=20, default='active')
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    # Billing (apps.billing). `paid_blocks` is what the school has bought for the current
    # term; `access_until` is copied from the latest payment and never recalculated.
    paid_blocks = models.PositiveIntegerField(default=0)
    access_until = models.DateField(null=True, blank=True)
    # The count given at onboarding, used for the first quote until real students are added.
    declared_students = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def portal_url(self):
        """Where this school's own portal lives, or '' when no domain is configured."""
        from django.conf import settings
        domain = (getattr(settings, 'PLATFORM_DOMAIN', '') or '').strip()
        if not domain or not self.subdomain:
            return ''
        return f'https://{self.subdomain}.{domain}'

    def __str__(self):
        return self.name
