"""The scheduled reminder scan.

Reminders go out 30 and 7 days before the next term resumes, on the day it resumes,
and on day 14 of the grace window. Each one is sent at most once a day per school.
"""
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

from apps.schools.models import School
from .emails import send_reminder
from .services import GRACE_DAYS, billing_state, school_billing

DEDUPE_SECONDS = 12 * 60 * 60


def _send_once(school, kind, days):
    key = f'billing:reminder:{school.pk}:{kind}:{days}'
    if cache.get(key):
        return False
    sent = send_reminder(school, kind, days)
    if sent:
        cache.set(key, True, DEDUPE_SECONDS)
    return sent


def run(today=None):
    """Send whatever is due today. Returns how many went out."""
    today = today or timezone.localdate()
    sent = 0
    schools = School.objects.exclude(status__in=('suspended', 'inactive')).select_related()
    for school in schools:
        info = school_billing(school.pk)
        access_until = info.get('access_until')
        if access_until is None:
            continue
        state = billing_state(access_until, today)
        resumes_on = access_until - timedelta(days=GRACE_DAYS)
        to_start = (resumes_on - today).days
        if state == 'active' and to_start in (30, 7):
            sent += bool(_send_once(school, 'renewal', to_start))
        elif state == 'grace':
            grace_day = (today - resumes_on).days
            if grace_day == 0:
                sent += bool(_send_once(school, 'started', 0))
            elif grace_day == 14:
                sent += bool(_send_once(school, 'grace', GRACE_DAYS - grace_day))
    return sent
