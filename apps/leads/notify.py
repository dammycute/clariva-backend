"""Tell the owner about a new demo request by email, through Resend's HTTP API."""
import logging

from django.conf import settings

from apps.base.mail import send_email

logger = logging.getLogger('apps')


def recipients():
    """Who hears about a new request: DEMO_NOTIFY_EMAIL (a comma-separated list) when set,
    otherwise the platform admins, whose addresses are already in the database. A request
    that is saved but silently unheard is the bug this avoids."""
    configured = [a.strip() for a in (settings.DEMO_NOTIFY_EMAIL or '').split(',') if a.strip()]
    if configured:
        return configured
    from apps.accounts.models import User
    return list(User.objects.filter(role='super_admin', is_active=True).exclude(email='')
                .values_list('email', flat=True))


def notify(lead) -> bool:
    """Send the email. Returns False, and never raises, if it is not set up or fails:
    the request is already saved, so a mail problem must not lose it."""
    if not getattr(settings, 'RESEND_API_KEY', ''):
        return False
    to = recipients()
    if not to:
        logger.warning('Demo request %s saved but nobody is set to be emailed', lead.pk)
        return False
    lines = [
        f'School: {lead.school_name}', f'Name: {lead.name}', f'Role: {lead.get_role_display()}',
        f'Phone: {lead.phone}', f'Email: {lead.email or "not given"}',
        f'Students: {lead.students if lead.students else "not given"}',
        '', lead.message or '(no message)',
    ]
    subject = f'Clariva demo request: {lead.school_name}'.replace('\n', ' ')[:200]
    return send_email(to, subject, '\n'.join(lines), reply_to=lead.email)
