from django.db import models

from apps.base.models import BaseUUIDModel
from apps.schools.models import TERM_CHOICES

PROVIDER_CHOICES = [
    ('paystack', 'Paystack'),
    ('manual', 'Manual'),
]

KIND_CHOICES = [
    ('new', 'New'),
    ('renewal', 'Renewal'),
    ('upgrade', 'Upgrade'),
    ('grant', 'Grant'),
]

PAYMENT_STATUSES = [
    ('pending', 'Pending'),
    ('paid', 'Paid'),
    ('failed', 'Failed'),
    ('abandoned', 'Abandoned'),
]


class TermCalendar(BaseUUIDModel):
    """When a term resumes, for one state (or one school that resumes on its own dates).

    `school` is empty for the state default. A row with `school` set overrides the
    state's date for that school only.
    """

    state = models.ForeignKey(
        'locations.State', on_delete=models.CASCADE, related_name='term_calendars',
    )
    school = models.ForeignKey(
        'schools.School', on_delete=models.CASCADE, null=True, blank=True,
        related_name='term_calendars',
        help_text='Set for a per-school override; empty for the state default.',
    )
    academic_year = models.CharField(max_length=20, help_text='e.g. 2026/2027')
    term = models.CharField(max_length=50, choices=TERM_CHOICES)
    resumes_on = models.DateField()
    provisional = models.BooleanField(
        default=False, help_text='Set until the ministry confirms the date.',
    )
    # Proof: the state's official notice, and who confirmed the date from it.
    source_url = models.URLField(max_length=500, blank=True, default='')
    confirmed_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['academic_year', 'term', 'state__name']
        verbose_name = 'term calendar'
        constraints = [
            models.UniqueConstraint(
                fields=['state', 'school', 'academic_year', 'term'],
                name='unique_term_calendar',
            ),
        ]

    def __str__(self):
        who = self.school.name if self.school_id else self.state.name
        return f'{who} — {self.term} {self.academic_year}'


class Payment(BaseUUIDModel):
    """One attempt to buy blocks for one term. The dates are frozen at payment time."""

    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, related_name='payments')
    reference = models.CharField(max_length=100, unique=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default='paystack')
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default='new')
    status = models.CharField(max_length=20, choices=PAYMENT_STATUSES, default='pending')
    amount = models.BigIntegerField(help_text='Kobo. Taken from the database, never from the browser.')
    blocks_after = models.PositiveIntegerField(default=0, help_text='Blocks the school has after this payment.')
    students_at_payment = models.PositiveIntegerField(default=0)
    academic_year = models.CharField(max_length=20)
    term = models.CharField(max_length=50, choices=TERM_CHOICES)
    covers_from = models.DateField()
    access_until = models.DateField(help_text='Saved now; a later calendar change does not move it.')
    channel = models.CharField(max_length=30, blank=True, default='')
    paid_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        'accounts.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='payments_created',
    )
    note = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.reference} — {self.school.name} ({self.status})'

    @property
    def amount_naira(self):
        return self.amount / 100
