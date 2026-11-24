"""Emails around billing: a receipt after a payment, and the reminders before a new term.

Uses Resend's HTTP API directly, like the demo-request email, so there is no extra package.
Every send is best effort: a mail problem must never lose or undo a payment.
"""
import json
import logging
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger('apps')


def send_email(to, subject, text) -> bool:
    key = getattr(settings, 'RESEND_API_KEY', '')
    sender = getattr(settings, 'BILLING_FROM_EMAIL', '') or settings.DEMO_FROM_EMAIL
    if not (key and to):
        return False
    payload = {'from': sender, 'to': [to], 'subject': subject[:200], 'text': text}
    req = Request(
        'https://api.resend.com/emails', data=json.dumps(payload).encode(), method='POST',
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                 'User-Agent': 'clariva-backend'},
    )
    try:
        urlopen(req, timeout=5).close()
        return True
    except Exception as exc:
        logger.warning('Billing email failed: %s', type(exc).__name__)
        return False


def admin_email(school):
    from apps.accounts.models import User
    user = User.objects.filter(school=school, role='school_admin').exclude(email='').first()
    return user.email if user else ''


def send_receipt(payment):
    to = admin_email(payment.school)
    if not to:
        return False
    naira = f'₦{payment.amount // 100:,}'
    text = '\n'.join([
        f'Thank you — your payment for {payment.school.name} is confirmed.',
        '',
        f'Reference: {payment.reference}',
        f'Amount: {naira}',
        f'Term: {payment.term} {payment.academic_year}',
        f'Covers until: {payment.access_until:%d %b %Y}',
        f'Student places: {payment.blocks_after * 50 + 10}',
        '',
        'You can see this payment any time on the Billing page of your portal.',
    ])
    return send_email(to, f'Receipt: {naira} received for {payment.term}', text)


def send_reminder(school, kind, days):
    to = admin_email(school)
    if not to:
        return False
    if kind == 'renewal':
        subject = f'{days} days until the new term — renew {school.name}'
        body = (f'The next term resumes in {days} days. Pay for it from the Billing page so '
                f'nothing stops for your students and staff.')
    elif kind == 'started':
        subject = f'The new term has resumed — {school.name}'
        body = ('The new term has resumed. You have three weeks to pay for it; the portal '
                'stays fully open until then. Pay from the Billing page.')
    else:                                    # grace
        subject = f'{days} days left to pay for {school.name}'
        body = (f'Your school\'s payment window closes in {days} days. After that, admins can '
                f'still read and pay, but changes are blocked. Pay from the Billing page.')
    return send_email(to, subject, body)
