"""One device at a time for students.

A student's sign-in gets a session id. It is saved on the user and written into the tokens
(the `sid` claim). A newer sign-in replaces it, so the older tokens stop working. Signing out,
or a staff member pressing "sign out of all devices", replaces it with a fresh id nobody holds.

A user with no saved session id is not locked to anything. That covers staff, schools that turn
the rule off, and students who have not signed in since the rule was added.
"""
import re
import uuid
from datetime import timedelta

from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import APIException


class ExamInProgressElsewhere(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'exam_in_progress_elsewhere'
    default_detail = {
        'detail': ('This account is taking an exam on another device. Finish the exam there first, '
                   'or ask your teacher to sign you out of that device.'),
        'code': 'exam_in_progress_elsewhere',
    }


def device_label(user_agent: str) -> str:
    """A short readable name such as 'Chrome on Android', from the browser's user agent."""
    ua = user_agent or ''
    browser = next((name for pat, name in (
        (r'Edg/', 'Edge'), (r'OPR/|Opera', 'Opera'), (r'SamsungBrowser', 'Samsung Internet'),
        (r'Firefox/', 'Firefox'), (r'Chrome/|CriOS', 'Chrome'), (r'Safari/', 'Safari'),
    ) if re.search(pat, ua)), 'Browser')
    system = next((name for pat, name in (
        (r'Android', 'Android'), (r'iPhone|iPad|iPod', 'iOS'), (r'Windows', 'Windows'),
        (r'Mac OS X|Macintosh', 'Mac'), (r'Linux', 'Linux'),
    ) if re.search(pat, ua)), 'unknown system')
    return f'{browser} on {system}'


def applies(user) -> bool:
    """Is this user held to one device? Students of a school that has the rule on."""
    return bool(user.role == 'student' and user.school_id and user.school.single_device_students)


def _exam_running(user) -> bool:
    """Is the student in the middle of a CBT exam attempt?"""
    from apps.exams.cbt import OFFLINE_GRACE_SECONDS
    from apps.exams.models import ExamSession
    cutoff = timezone.now() - timedelta(seconds=OFFLINE_GRACE_SECONDS)
    return ExamSession.objects.filter(student=user, status='active').exclude(deadline__lt=cutoff).exists()


def start_session(user, request=None, device_id: str = ''):
    """Make this sign-in the student's only one. Returns the session id for the tokens.

    Returns None when the rule does not apply to this user. Raises ExamInProgressElsewhere
    when another device holds the account during an exam; the same device may always sign in again.
    """
    device_id = (device_id or '')[:64]
    if not applies(user):
        if user.active_session_id or user.session_device_id:      # the rule was turned off: let go
            user.active_session_id, user.session_device_id = None, ''
            user.save(update_fields=['active_session_id', 'session_device_id'])
        return None

    holder = user.session_device_id
    if holder and holder != device_id and _exam_running(user):
        raise ExamInProgressElsewhere()

    user.active_session_id = uuid.uuid4()
    user.session_device_id = device_id
    user.session_started_at = timezone.now()
    ua = request.META.get('HTTP_USER_AGENT', '') if request is not None else ''
    user.session_device = device_label(ua)
    user.save(update_fields=['active_session_id', 'session_device_id', 'session_started_at', 'session_device'])
    return str(user.active_session_id)


def end_session(user) -> None:
    """Sign the student out of every device. A fresh id nobody holds replaces the old one."""
    if user.role != 'student':
        return
    user.active_session_id = uuid.uuid4()
    user.session_device_id = ''
    user.session_device = ''
    user.session_started_at = None
    user.save(update_fields=['active_session_id', 'session_device_id', 'session_device', 'session_started_at'])


def is_current(user, sid) -> bool:
    """Does a token carrying `sid` still belong to the user's one live session?"""
    if user.role != 'student' or user.active_session_id is None:
        return True
    return bool(sid) and str(user.active_session_id) == str(sid)
