"""Send plain-text email through Resend's HTTP API, so there is no extra package.

Every caller treats a send as best effort: a mail problem must never undo the work the
email is about, so this returns False instead of raising.
"""
import json
import logging
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger('apps')


def send_email(to, subject, text, reply_to='') -> bool:
    """Send one email to an address or a list of them. False when mail is not set up or fails."""
    key = getattr(settings, 'RESEND_API_KEY', '')
    sender = (getattr(settings, 'BILLING_FROM_EMAIL', '') or getattr(settings, 'DEMO_FROM_EMAIL', '')
              or 'Clarriva <onboarding@resend.dev>')
    recipients = [to] if isinstance(to, str) else list(to or [])
    recipients = [r for r in recipients if r]
    if not (key and recipients):
        return False
    payload = {'from': sender, 'to': recipients, 'subject': subject[:200], 'text': text}
    if reply_to:
        payload['reply_to'] = reply_to
    req = Request(
        'https://api.resend.com/emails', data=json.dumps(payload).encode(), method='POST',
        # Resend's firewall rejects the default Python user agent.
        headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json',
                 'User-Agent': 'clarriva-backend'},
    )
    try:
        urlopen(req, timeout=5).close()
        return True
    except Exception as exc:            # network, bad key, or Resend down; details stay out of the log
        logger.warning('Email failed: %s %s', type(exc).__name__, getattr(exc, 'code', ''))
        return False
