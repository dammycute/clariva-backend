"""Which term dates the platform admins still have to enter, the emails that chase them,
and the checks on what they type.

For a session an admin enters four dates: when each of its three terms starts, and when the
next session's 1st term starts (a paid term ends three weeks after the *next* one starts).
The three are wanted as soon as the session begins. Every later date is wanted 30 days
before schools can pay for the term that depends on it.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from apps.base.mail import send_email
from apps.locations.models import State
from apps.schools.models import School
from .exceptions import PaymentProblem
from .models import Payment, TermCalendar
from .services import GRACE_DAYS, PAYMENT_WINDOW_DAYS, TERM_ORDER, academic_year_for, invalidate, next_term

logger = logging.getLogger('apps')

REMIND_DAYS_BEFORE = PAYMENT_WINDOW_DAYS + 30      # before the term that depends on the date starts
SESSION_STARTS_IN_MONTH = 9
WEEKLY_ON = 0                                      # Monday: when only unconfirmed dates are left
# Days between one term's start and the next. Outside this, the admin is asked to check.
USUAL_GAP = (56, 180)


def _slot_key(academic_year, term):
    return academic_year, TERM_ORDER.index(term)


def previous_term(academic_year, term):
    index = TERM_ORDER.index(term)
    if index:
        return academic_year, TERM_ORDER[index - 1]
    start = int(academic_year.split('/')[0]) - 1
    return academic_year_for(start), TERM_ORDER[-1]


# ---------------------------------------------------------------- what is due

def current_session(rows, today):
    """The first year of the session we are in. A state that resumed early moves on early."""
    year = today.year if today.month >= SESSION_STARTS_IN_MONTH else today.year - 1
    started = [int(y.split('/')[0]) for (y, t), row in rows.items()
               if t == TERM_ORDER[0] and row.resumes_on <= today]
    return max([year, *started])


def due_dates(rows, today):
    """Dates one state still needs, from its {(academic_year, term): row} calendar.

    Returns (missing, unconfirmed): two lists of (academic_year, term).
    """
    year = academic_year_for(current_session(rows, today))
    slots = [(year, term) for term in TERM_ORDER]
    last = slots[-1]
    while last in rows and today >= rows[last].resumes_on - timedelta(days=REMIND_DAYS_BEFORE):
        last = next_term(*last)
        slots.append(last)

    missing, unconfirmed = [], []
    for slot in slots:
        row = rows.get(slot)
        if row is None:
            following = rows.get(next_term(*slot))
            if following is None or following.resumes_on > today:     # not a term that is already over
                missing.append(slot)
        elif row.provisional:
            unconfirmed.append(slot)
    return missing, unconfirmed


def states_needing_dates(today=None):
    """Only states that have schools. Also names schools whose state is not on the list,
    because they cannot pay until it is corrected."""
    today = today or timezone.localdate()
    by_name = {s.name.lower(): s for s in State.objects.all()}
    schools_in, unmatched = {}, []
    for name, state_name in School.objects.exclude(status__in=('suspended', 'inactive')).values_list('name', 'state'):
        state = by_name.get((state_name or '').strip().lower())
        if state is None:
            unmatched.append(name)
        else:
            schools_in[state] = schools_in.get(state, 0) + 1

    calendars = {}
    for row in TermCalendar.objects.filter(school__isnull=True, state__in=list(schools_in)):
        calendars.setdefault(row.state_id, {})[(row.academic_year, row.term)] = row

    result = []
    for state in sorted(schools_in, key=lambda s: s.name):
        missing, unconfirmed = due_dates(calendars.get(state.pk, {}), today)
        if missing or unconfirmed:
            result.append({'state': state, 'schools': schools_in[state],
                           'missing': missing, 'unconfirmed': unconfirmed})
    return result, sorted(unmatched)


# ---------------------------------------------------------------- the emails

def admins():
    from apps.accounts.models import User
    return User.objects.filter(role='super_admin', is_active=True).exclude(email='').order_by('email')


def recipients():
    """The admins chosen to get calendar emails; everyone by default. Never nobody."""
    chosen = [u.email for u in admins() if u.receives_calendar_reminders]
    return chosen or [u.email for u in admins()]


def _words(slots):
    return ', '.join(f'{term} {year}' for year, term in slots)


def _digest_text(states, unmatched):
    lines = ['Schools are billed from the term dates you enter. These still need you.', '']
    missing = [s for s in states if s['missing']]
    if missing:
        lines.append('MISSING (schools cannot pay for the terms that depend on these):')
        lines += [f"- {s['state'].name} ({s['schools']} school(s)): {_words(s['missing'])}" for s in missing]
        lines.append('')
    unconfirmed = [s for s in states if s['unconfirmed']]
    if unconfirmed:
        lines.append('PROVISIONAL (confirm with the state notice and its link):')
        lines += [f"- {s['state'].name}: {_words(s['unconfirmed'])}" for s in unconfirmed]
        lines.append('')
    if unmatched:
        lines.append('SCHOOLS WITH NO STATE FROM THE LIST (they cannot pay until it is set):')
        lines += [f'- {name}' for name in unmatched]
        lines.append('')
    domain = getattr(settings, 'PLATFORM_DOMAIN', '')
    lines.append(f'Enter them here: https://{domain}/admin/calendars' if domain else 'Open Term calendars in the admin console.')
    return '\n'.join(lines)


def _send(states, unmatched):
    needing = len([s for s in states if s['missing']])
    subject = (f'Clarriva: term dates missing for {needing} state(s)' if needing
               else 'Clarriva: term dates need attention')
    to = recipients()
    return bool(to) and send_email(to, subject, _digest_text(states, unmatched))


def send_digest(today=None):
    """One email a day while anything is missing; Mondays only when dates are merely
    unconfirmed. Run by the daily reminder job. Returns how many emails went out."""
    today = today or timezone.localdate()
    states, unmatched = states_needing_dates(today)
    if not states and not unmatched:
        return 0
    urgent = unmatched or any(s['missing'] for s in states)
    if not urgent and today.weekday() != WEEKLY_ON:
        return 0
    key = f'billing:calendar-digest:{today.isoformat()}'
    if cache.get(key) or not _send(states, unmatched):
        return 0                                   # already sent today, or it failed: try again next run
    cache.set(key, True, 2 * 24 * 60 * 60)
    return 1


def alert_new_school(school, today=None):
    """Tell the admins at once when the first school in a state arrives and dates are missing."""
    name = (school.state or '').strip()
    others = School.objects.filter(state__iexact=name).exclude(pk=school.pk)
    if name and others.exists():
        return False
    states, unmatched = states_needing_dates(today)
    mine = [s for s in states if s['state'].name.lower() == name.lower() and s['missing']]
    unknown = [n for n in unmatched if n == school.name]
    return bool(mine or unknown) and _send(mine, unknown)


# ---------------------------------------------------------------- checking and applying dates

def check_order(rows, confirm_unusual=False):
    """Run inside the transaction that saved `rows`: dates must follow term order, and an
    odd gap needs the admin to say the date is right. Raising rolls the save back."""
    for row in rows:
        for neighbour, earlier in ((previous_term(row.academic_year, row.term), True),
                                   (next_term(row.academic_year, row.term), False)):
            found = TermCalendar.objects.filter(
                state=row.state, academic_year=neighbour[0], term=neighbour[1])
            other = (found.filter(school=row.school_id).first() if row.school_id else None) \
                or found.filter(school__isnull=True).first()
            if other is None:
                continue
            first, second = (other, row) if earlier else (row, other)
            gap = (second.resumes_on - first.resumes_on).days
            what = (f'{row.state.name}: {second.term} {second.academic_year} ({second.resumes_on:%d %b %Y}) '
                    f'and {first.term} {first.academic_year} ({first.resumes_on:%d %b %Y})')
            if gap <= 0:
                raise PaymentProblem(f'Dates are out of order. {what}.', code='dates_out_of_order')
            if not confirm_unusual and not USUAL_GAP[0] <= gap <= USUAL_GAP[1]:
                raise PaymentProblem(
                    f'Please check these dates: they are {gap} days apart. {what}. '
                    'If the dates are right, tick "Dates are correct" and save again.',
                    code='unusual_gap')


def extend_paid_on_estimate(row, old_date):
    """A provisional date turned out later. Payments that ran to the estimate now run to the
    real date. Nothing is ever shortened. Returns how many schools gained time."""
    if row.resumes_on <= old_date:
        return 0
    old_end = old_date + timedelta(days=GRACE_DAYS)
    new_end = row.resumes_on + timedelta(days=GRACE_DAYS)
    year, term = previous_term(row.academic_year, row.term)
    payments = Payment.objects.filter(
        academic_year=year, term=term, access_until=old_end, status__in=('paid', 'pending'),
        school__state__iexact=row.state.name).exclude(note__startswith='REVIEW:')
    if row.school_id:
        payments = payments.filter(school_id=row.school_id)
    else:
        own = TermCalendar.objects.filter(school__isnull=False, academic_year=row.academic_year,
                                          term=row.term).values_list('school_id', flat=True)
        payments = payments.exclude(school_id__in=list(own))      # they follow their own dates

    gained = set()
    for payment in payments:
        payment.access_until = new_end
        payment.note = (payment.note + f'\nExtended from {old_end} to {new_end}: the term date was confirmed.').strip()
        payment.save(update_fields=['access_until', 'note'])
        if School.objects.filter(pk=payment.school_id, access_until=old_end).update(access_until=new_end):
            invalidate(payment.school_id)
            gained.add(payment.school_id)
    return len(gained)
