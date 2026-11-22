"""Tell the owner about a new demo request by email, through Resend's HTTP API (no extra package)."""
import json
import logging
from urllib.request import Request, urlopen

from django.conf import settings

logger = logging.getLogger('apps')


def notify(lead) -> bool:
    """Send the email. Returns False, and never raises, if it is not set up or fails:
    the request is already saved, so a mail problem must not lose it."""
    if not (settings.RESEND_API_KEY and settings.DEMO_NOTIFY_EMAIL):
        return False
    lines = [
        f'School: {lead.school_name}', f'Name: {lead.name}', f'Role: {lead.get_role_display()}',
        f'Phone: {lead.phone}', f'Email: {lead.email or "not given"}',
        f'Students: {lead.students if lead.students else "not given"}',
        '', lead.message or '(no message)',
    ]
    payload = {
        'from': settings.DEMO_FROM_EMAIL,
        'to': [settings.DEMO_NOTIFY_EMAIL],
        'subject': f'Clariva demo request: {lead.school_name}'.replace('\n', ' ')[:200],
        'text': '\n'.join(lines),
    }
    if lead.email:
        payload['reply_to'] = lead.email
    req = Request(
        'https://api.resend.com/emails', data=json.dumps(payload).encode(), method='POST',
        # Resend's firewall rejects the default Python user agent.
        headers={'Authorization': f'Bearer {settings.RESEND_API_KEY}', 'Content-Type': 'application/json',
                 'User-Agent': 'clariva-backend'})
    try:
        urlopen(req, timeout=5).close()
        return True
    except Exception as exc:                      # network, bad key, or Resend down; details stay out of the log
        logger.warning('Demo request email failed: %s', type(exc).__name__)
        return False
