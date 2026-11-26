"""The billing rules, in one place.

Price: ₦30,000 per term for each block of 50 students. The 10 free places belong to
the school, not to each block: one block covers 60 students, two cover 110, six cover
310. A paid term covers the school until 21 days after the next term resumes.

Nothing here reads the request; the views and the authentication hook call in.
"""
import logging
import math
import re
from datetime import date, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import SAFE_METHODS

from apps.schools.models import School
from .exceptions import BillingBlocked, PaymentProblem, StudentLimitReached
from .models import Payment, TermCalendar

PRICE_PER_BLOCK = 30000          # naira
BLOCK_SIZE = 50
BUFFER_STUDENTS = 10             # free places for the school, once — not per block
GRACE_DAYS = 21                  # after the next term resumes
PAYMENT_WINDOW_DAYS = 60         # how early a school may pay
CACHE_TTL = 60                   # seconds; the entitlement check reads this

TERM_ORDER = ['1st Term', '2nd Term', '3rd Term']

logger = logging.getLogger('apps')

# An attempt that is already running must be able to finish, whatever happens to the bill.
EXAM_SAVE_OR_SUBMIT = re.compile(r'^/api/exams/sessions/[0-9a-fA-F-]+/(save|submit)/$')
EXAM_START = re.compile(r'^/api/exams/exams/([0-9a-fA-F-]+)/start/$')

# Paths that must keep working for a school that has not paid: signing in, the billing
# pages themselves, the public parent portal, health checks, and the Django admin.
EXEMPT_PREFIXES = (
    '/api/auth/',
    '/api/billing/',
    '/api/portal/',
    '/health/',
    '/admin/',
)


# ---------------------------------------------------------------- the price

def blocks_for(students: int) -> int:
    """How many blocks of 50 a school with this many students pays for.

    The buffer is subtracted once, whatever the size of the school: 60 students is
    one block, 61 starts the second, 300 is six and 700 is fourteen. Zero is refused.
    """
    if students is None or students < 1:
        raise ValueError('A school needs at least one student.')
    return max(1, math.ceil(max(students - BUFFER_STUDENTS, 1) / BLOCK_SIZE))


def limit_for_blocks(blocks: int) -> int:
    """The most students a plan covers."""
    return blocks * BLOCK_SIZE + BUFFER_STUDENTS


def price_for_blocks(blocks: int) -> int:
    """Naira."""
    return blocks * PRICE_PER_BLOCK


def students_in_school(school) -> int:
    """Active students. Students who left or graduated free up their places."""
    from apps.accounts.models import User
    return User.objects.filter(
        school=school, role='student', student_profile__student_status='active',
    ).count()


def quote_students(school) -> int:
    """What the next bill is based on.

    A school that has not added its students yet is quoted the number it gave at
    onboarding; after that the real active count wins.
    """
    counted = students_in_school(school)
    return counted or school.declared_students or 0


# ---------------------------------------------------------------- the calendar

def _start_year(academic_year: str) -> int:
    try:
        return int(str(academic_year).split('/')[0])
    except (ValueError, AttributeError, IndexError):
        return timezone.localdate().year


def academic_year_for(start_year: int) -> str:
    return f'{start_year}/{start_year + 1}'


def next_term(academic_year: str, term: str):
    """The term after this one, rolling into the next academic year at the third."""
    index = TERM_ORDER.index(term) if term in TERM_ORDER else 0
    if index == len(TERM_ORDER) - 1:
        return academic_year_for(_start_year(academic_year) + 1), TERM_ORDER[0]
    return academic_year, TERM_ORDER[index + 1]


def calendar_entry(state_name: str, school, academic_year: str, term: str):
    """The date a term resumes: the school's own override first, then the state's."""
    if not state_name:
        return None
    rows = TermCalendar.objects.filter(
        state__name__iexact=state_name, academic_year=academic_year, term=term,
    )
    if school is not None and school.pk:
        own = rows.filter(school=school).first()
        if own:
            return own
    return rows.filter(school__isnull=True).first()


def term_window(state_name: str, school, academic_year: str, term: str):
    """Everything a school is buying when it pays for one term, or None if a date is missing."""
    this = calendar_entry(state_name, school, academic_year, term)
    if this is None:
        return None
    next_year, next_name = next_term(academic_year, term)
    following = calendar_entry(state_name, school, next_year, next_name)
    if following is None:
        return None
    return {
        'academic_year': academic_year,
        'term': term,
        'resumes_on': this.resumes_on,
        # provisional if either date it is built from is still unconfirmed
        'provisional': this.provisional or following.provisional,
        'next_academic_year': next_year,
        'next_term': next_name,
        'next_resumes_on': following.resumes_on,
        'access_until': following.resumes_on + timedelta(days=GRACE_DAYS),
    }


def term_payments(school):
    """Paid records that bought a term. Upgrades add places, and a date-only grant adds
    time; neither buys a term. Records held for review are left out too."""
    return (Payment.objects.filter(school=school, status='paid')
            .exclude(kind='upgrade').exclude(kind='grant', amount=0)
            .exclude(note__startswith=REVIEW))


def current_term_paid(school):
    """The term the school's access belongs to: what an upgrade adds places to."""
    last = term_payments(school).order_by('-access_until', '-paid_at').first()
    if last is not None:
        return last.academic_year, last.term
    return school.current_academic_year, school.current_term


def term_to_pay(school):
    """The term a payment now would buy: the one after the last paid term."""
    last = term_payments(school).order_by('-access_until', '-paid_at').first()
    if last is not None:
        return next_term(last.academic_year, last.term)
    return school.current_academic_year, school.current_term


# ---------------------------------------------------------------- entitlement

def billing_state(access_until, today=None):
    """pending, active, grace or lapsed — from the access date alone."""
    today = today or timezone.localdate()
    if access_until is None:
        return 'pending'
    grace_starts = access_until - timedelta(days=GRACE_DAYS)
    if today < grace_starts:
        return 'active'
    if today <= access_until:
        return 'grace'
    return 'lapsed'


def school_billing(school_id):
    """The two numbers the per-request check needs, cached so it costs no query."""
    key = f'billing:school:{school_id}'
    data = cache.get(key)
    if data is None:
        row = School.objects.filter(pk=school_id).values(
            'access_until', 'paid_blocks', 'status',
        ).first()
        data = row or {'access_until': None, 'paid_blocks': 0, 'status': 'active'}
        cache.set(key, data, CACHE_TTL)
    return data


def invalidate(school_id):
    cache.delete(f'billing:school:{school_id}')


def _finishing_an_exam(user, path) -> bool:
    """Saving, handing in, or reopening an attempt that is already running."""
    if EXAM_SAVE_OR_SUBMIT.match(path):
        return True                       # the views check the attempt is the student's own and open
    start = EXAM_START.match(path)
    if not start:
        return False
    from apps.exams.models import ExamSession
    try:
        return ExamSession.objects.filter(exam_id=start.group(1), student=user, status='active').exists()
    except (ValueError, ValidationError):
        return False


def enforce(user, request):
    """Called from authentication on every request. Raises 402 when the school may not go on."""
    if not getattr(settings, 'BILLING_ENFORCE', False):
        return
    if not user or not user.is_authenticated:
        return
    if getattr(user, 'role', None) == 'super_admin' or user.is_superuser:
        return
    if not user.school_id:
        return

    path = request.path or ''
    if path.startswith(EXEMPT_PREFIXES) or path == f'/api/schools/{user.school_id}/':
        return
    if request.method in ('OPTIONS', 'HEAD'):
        return

    info = school_billing(user.school_id)
    if info.get('status') == 'suspended':
        return                                  # the existing suspension message owns this
    state = billing_state(info.get('access_until'))
    if state == 'pending':
        raise BillingBlocked(
            'billing_pending',
            'Your school has not paid for this term yet. Pay to open the portal.',
        )
    if state == 'lapsed' and request.method not in SAFE_METHODS and not _finishing_an_exam(user, path):
        raise BillingBlocked(
            'billing_lapsed',
            'Your school\'s subscription has lapsed. Admins can read and pay; '
            'changes are blocked until it is paid.',
        )


# ---------------------------------------------------------------- capacity

def capacity(school):
    """Students used, places included in the plan, and places left."""
    used = students_in_school(school)
    blocks = school.paid_blocks
    limit = limit_for_blocks(blocks) if blocks else 0
    return {'students': used, 'limit': limit, 'remaining': max(limit - used, 0)}


def check_capacity(school, adding: int = 1):
    """Raise 409 if `adding` more students would pass what the plan covers."""
    if not getattr(settings, 'BILLING_ENFORCE', False):
        return
    if transaction.get_connection().in_atomic_block:
        # Callers create the student inside the same transaction, so a second request waits here.
        school = School.objects.select_for_update().get(pk=school.pk)
    if not school.paid_blocks:
        return                                  # nothing bought: the 402 gate owns this school
    room = capacity(school)
    if adding > room['remaining']:
        left = room['remaining']
        places = f'{left} place' if left == 1 else f'{left} places'
        raise StudentLimitReached(
            f'Your plan covers {room["limit"]} students and {room["students"]} are enrolled. '
            f'You have {places} left. Upgrade to add more.'
        )


# ---------------------------------------------------------------- paying

def new_reference(school) -> str:
    """Only letters, digits and dashes: what Paystack accepts."""
    import secrets
    return f'CLV-{str(school.pk).replace("-", "")[:8]}-{secrets.token_hex(6)}'


def create_payment(school, kind, students, academic_year, term, amount, blocks_after,
                   covers_from, access_until, created_by=None, note='', provider='paystack'):
    """Save a pending payment. `amount` is kobo and comes from the server's own numbers."""
    return Payment.objects.create(
        school=school, reference=new_reference(school), provider=provider, kind=kind,
        amount=amount, blocks_after=blocks_after, students_at_payment=students,
        academic_year=academic_year, term=term, covers_from=covers_from,
        access_until=access_until, created_by=created_by, note=note,
    )


REVIEW = 'REVIEW:'


def _needs_review(payment, school):
    """Why a confirmed payment must not change the school, or '' when it can be applied.

    The money has arrived either way. Applying it would take something away or charge
    twice, so it is kept, marked for a person to refund or credit.
    """
    if payment.kind != 'upgrade' and term_payments(school).exclude(pk=payment.pk).filter(
            academic_year=payment.academic_year, term=payment.term).exists():
        return f'{payment.term} {payment.academic_year} was already paid. Refund or credit this payment.'
    if school.access_until and payment.access_until < school.access_until:
        return 'It was started before a newer payment and covers less time. Refund or credit it.'
    if payment.kind == 'upgrade' and payment.blocks_after <= school.paid_blocks:
        return 'The school already has these places. Refund or credit this payment.'
    return ''


def fulfil_payment(payment, payload):
    """Write a verified Paystack payload onto the payment and the school.

    Called after a network verify, never while holding a lock.
    """
    data = payload.get('data') if isinstance(payload, dict) and 'data' in payload else payload
    if not isinstance(data, dict):
        raise PaymentProblem('Paystack did not confirm this payment.')
    if data.get('status') != 'success':
        raise PaymentProblem(
            f'Paystack says this payment is {data.get("status") or "not complete"}.',
            code='payment_not_successful',
        )
    if data.get('currency') and data['currency'] != 'NGN':
        raise PaymentProblem('This payment was not in naira.', code='wrong_currency')
    try:
        amount = int(data.get('amount') or 0)
    except (TypeError, ValueError):
        amount = 0
    if amount != payment.amount:
        raise PaymentProblem(
            'The amount Paystack confirmed does not match this payment.',
            code='amount_mismatch',
        )
    reference = data.get('reference')
    if reference and reference != payment.reference:
        raise PaymentProblem('Paystack confirmed a different reference.', code='reference_mismatch')

    with transaction.atomic():
        # The school row first: two payments for one school are then settled one at a time.
        school = School.objects.select_for_update().get(pk=payment.school_id)
        locked = Payment.objects.select_for_update().get(pk=payment.pk)
        if locked.status == 'paid':
            return locked
        problem = _needs_review(locked, school)
        locked.status = 'paid'
        locked.channel = (data.get('channel') or '')[:30]
        paid_at = data.get('paid_at')
        locked.paid_at = parse_datetime(paid_at) if paid_at else timezone.now()
        if problem:
            locked.note = f'{REVIEW} {problem}'
        locked.save(update_fields=['status', 'channel', 'paid_at', 'note'])

        if problem:
            logger.warning('Payment %s needs review: %s', locked.reference, problem)
        else:
            School.objects.filter(pk=locked.school_id).update(
                paid_blocks=locked.blocks_after,
                access_until=locked.access_until,
                plan='basic',
                trial_ends_at=None,
            )
            # Never un-suspend a school as a side effect of a payment.
            School.objects.filter(pk=locked.school_id, status='pending').update(status='active')

    invalidate(locked.school_id)
    try:
        from .emails import send_receipt
        send_receipt(locked)
    except Exception:                                  # a mail problem must not undo a payment
        pass
    return locked


def apply_manual_payment(school, blocks, academic_year, term, access_until, covers_from,
                         amount, kind, note, user):
    """A logged payment the super admin enters: a grant, an extension, or a bank transfer."""
    payment = Payment.objects.create(
        school=school, reference=f'MAN-{str(school.pk).replace("-", "")[:8]}-{int(timezone.now().timestamp())}',
        provider='manual', kind=kind, status='paid', amount=amount, blocks_after=blocks,
        students_at_payment=students_in_school(school), academic_year=academic_year, term=term,
        covers_from=covers_from, access_until=access_until, paid_at=timezone.now(),
        created_by=user, note=note,
    )
    School.objects.filter(pk=school.pk).update(
        paid_blocks=blocks, access_until=access_until, plan='basic', trial_ends_at=None,
    )
    School.objects.filter(pk=school.pk, status='pending').update(status='active')
    invalidate(school.pk)
    return payment


# ---------------------------------------------------------------- the pay page

def status_payload(school, today=None):
    """Everything the pay page and the billing page show."""
    today = today or timezone.localdate()
    info = school_billing(school.pk)
    access_until = info.get('access_until')
    state = 'suspended' if info.get('status') == 'suspended' else billing_state(access_until, today)

    counted = students_in_school(school)
    quoted = counted or school.declared_students or 0
    paid_blocks = school.paid_blocks
    room = capacity(school)

    needed_blocks = blocks_for(quoted) if quoted else 0
    payload = {
        'school': {
            'id': str(school.pk), 'name': school.name, 'state': school.state,
            'status': info.get('status'), 'current_term': school.current_term,
            'current_academic_year': school.current_academic_year,
        },
        'enforce': bool(getattr(settings, 'BILLING_ENFORCE', False)),
        'state': state,
        'access_until': access_until,
        'students': counted,
        'declared_students': school.declared_students,
        'quote_students': quoted,
        'paid_blocks': paid_blocks,
        'blocks_needed': needed_blocks,
        'limit': room['limit'],
        'remaining': room['remaining'],
        'price_per_block': PRICE_PER_BLOCK,
        'price_per_term': price_for_blocks(needed_blocks) if needed_blocks else 0,
        'days_left': (access_until - today).days if access_until else None,
        'upgrade': None,
        'next_term': None,
        'payment_opens_on': None,
        'can_pay': False,
        'blocked_reason': None,
        'dates_provisional': False,
    }

    if state == 'suspended':
        payload['blocked_reason'] = 'suspended'
        return payload
    if not quoted:
        payload['blocked_reason'] = 'no_students'
        return payload

    if paid_blocks and needed_blocks > paid_blocks:
        extra = needed_blocks - paid_blocks
        payload['upgrade'] = {
            'blocks': needed_blocks,
            'extra_blocks': extra,
            'amount': price_for_blocks(extra),
        }

    year, term = term_to_pay(school)
    window = term_window(school.state, school, year, term)
    if window is None:
        payload['blocked_reason'] = 'missing_calendar'      # billing never guesses a term's length
        return payload

    payload['dates_provisional'] = window['provisional']
    payload['next_term'] = {
        'academic_year': window['academic_year'],
        'term': window['term'],
        'resumes_on': window['resumes_on'].isoformat(),
        'provisional': window['provisional'],
        'next_academic_year': window['next_academic_year'],
        'next_term': window['next_term'],
        'next_resumes_on': window['next_resumes_on'].isoformat(),
        'access_until': window['access_until'].isoformat(),
    }
    opens_on = window['resumes_on'] - timedelta(days=PAYMENT_WINDOW_DAYS)
    payload['payment_opens_on'] = opens_on.isoformat()
    payload['can_pay'] = (
        today >= opens_on or state in ('pending', 'grace', 'lapsed')
    )
    if not payload['can_pay']:
        payload['blocked_reason'] = 'window_closed'
    return payload
