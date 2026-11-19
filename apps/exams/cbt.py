"""CBT rules that touch the database: who may sit an exam, when an attempt ends, how it is
finalised, and how scores reach grades. Views stay thin and call these."""
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .marking import mark_answers
from .models import Exam, ExamSession, Question

# Extra seconds after an attempt's deadline for the last autosave to arrive before the
# server closes the attempt for the student.
CLOSE_GRACE_SECONDS = 60
# A manual Submit is still accepted this long after the deadline, but flagged as late.
LATE_GRACE_MINUTES = 5

CA_DEFAULT_MAX = 30
EXAM_DEFAULT_MAX = 100


# ── Who may sit an exam ──────────────────────────────────────────

def _student_class(student):
    profile = getattr(student, 'student_profile', None)
    return getattr(profile, 'class_group', None) if profile else None


def student_may_sit(exam: Exam, student) -> bool:
    """A student may sit an exam made for their class. An exam with no class chosen is open
    only to the year group of its subject, and to nobody if it has neither."""
    if exam.school_id != student.school_id:
        return False
    cls = _student_class(student)
    if cls is None:
        return False
    classes = list(exam.classes.all())          # uses the prefetched list when there is one
    if any(c.pk == cls.pk for c in classes):
        return True
    if classes:
        return False
    if exam.class_group_id:                      # older exams that only have the single class
        return exam.class_group_id == cls.pk
    subject = exam.subject
    return bool(subject and subject.year_group and cls.year_group == subject.year_group)


def exam_is_open(exam: Exam, now=None) -> bool:
    now = now or timezone.now()
    if exam.status != 'published':
        return False
    if exam.start_time and now < exam.start_time:
        return False
    if exam.end_time and now > exam.end_time:
        return False
    return True


# ── Time ─────────────────────────────────────────────────────────

def attempt_deadline(exam: Exam, started_at):
    """The server's own end time for one attempt."""
    candidates = []
    if exam.time_limit_enforced:
        candidates.append(started_at + timedelta(minutes=exam.duration_mins))
    if exam.end_time:
        candidates.append(exam.end_time)
    return min(candidates) if candidates else None


def seconds_left(session: ExamSession, now=None):
    now = now or timezone.now()
    if session.deadline is None:
        return None
    return max(0, int((session.deadline - now).total_seconds()))


def is_overdue(session: ExamSession, now=None) -> bool:
    now = now or timezone.now()
    return bool(session.deadline and now > session.deadline + timedelta(seconds=CLOSE_GRACE_SECONDS))


# ── Results visibility and grades ────────────────────────────────

def results_visible(exam: Exam) -> bool:
    return exam.release_mode == 'immediate' or exam.results_released


def component_max(school, component: str):
    """The maximum marks the school gave this component (CA 1, exam ...), else the old defaults."""
    config = getattr(school, 'grading_config', None)
    if config:
        for c in config.components or []:
            if c.get('key') == component and c.get('enabled', True) and c.get('max'):
                return Decimal(str(c['max']))
    return Decimal(EXAM_DEFAULT_MAX if component == 'exam' else CA_DEFAULT_MAX)


def post_grade(session: ExamSession) -> None:
    """Write this attempt's score into the student's Grade. An approved grade is never changed."""
    from apps.grades.models import Grade

    exam = session.exam
    if not (exam.component and exam.subject_id and session.total_marks):
        return
    maximum = component_max(exam.school, exam.component)
    scaled = (Decimal(session.score) / Decimal(session.total_marks) * maximum).quantize(Decimal('0.01'))

    grade, created = Grade.objects.get_or_create(
        school=exam.school, student=session.student, subject=exam.subject,
        term=exam.term or '', academic_year=exam.academic_year or '',
        defaults={exam.component: scaled},
    )
    if not created and grade.results_status != 'approved':
        setattr(grade, exam.component, scaled)
        grade.save()


# ── Finishing an attempt ─────────────────────────────────────────

@transaction.atomic
def finalize_session(session_id, answers=None, reason='student', now=None):
    """Mark and close one attempt. Safe to call twice: the second call changes nothing.

    reason: 'student' (they pressed Submit), 'time' (the deadline passed) or 'closed'
    (the exam was closed). Returns (session, did_finalize).
    """
    now = now or timezone.now()
    session = (ExamSession.objects.select_for_update()
               .select_related('exam', 'exam__school', 'exam__subject', 'student')
               .get(pk=session_id))
    if session.status != 'active':
        return session, False

    exam = session.exam
    saved = {str(a.question_id): a.answer for a in session.saved_answers.all()}
    merged = {**saved, **{str(k): v for k, v in (answers or {}).items()}}

    questions = list(Question.objects.filter(exam=exam))
    score, total = mark_answers(questions, merged)

    late = False
    if reason == 'student' and session.deadline:
        late = now > session.deadline + timedelta(minutes=LATE_GRACE_MINUTES)

    session.answers = merged
    session.score = score
    session.total_marks = total
    session.passed = (score / total * 100) >= exam.pass_mark if total else False
    session.submitted_at = now
    session.status = 'submitted'
    session.late_submission = late
    session.auto_submitted = reason != 'student'
    session.save()

    if results_visible(exam):
        post_grade(session)
    return session, True


def close_overdue_sessions(**filters) -> int:
    """Submit every running attempt whose deadline has passed. Called whenever an attempt or
    its exam is touched, so no background job is needed."""
    now = timezone.now()
    cutoff = now - timedelta(seconds=CLOSE_GRACE_SECONDS)
    ids = list(ExamSession.objects.filter(status='active', deadline__lt=cutoff, **filters)
               .values_list('id', flat=True))
    closed = 0
    for sid in ids:
        _, did = finalize_session(sid, reason='time', now=now)
        closed += int(did)
    return closed


def close_exam(exam: Exam) -> int:
    """Close the exam and submit every unfinished attempt. Returns how many were submitted."""
    exam.status = 'closed'
    exam.closed_at = timezone.now()
    exam.save(update_fields=['status', 'closed_at'])
    closed = 0
    for sid in list(ExamSession.objects.filter(exam=exam, status='active').values_list('id', flat=True)):
        _, did = finalize_session(sid, reason='closed')
        closed += int(did)
    return closed


@transaction.atomic
def release_results(exam: Exam) -> int:
    """Let students see their scores and write the grades. Returns how many grades were posted."""
    exam.results_released = True
    exam.results_released_at = timezone.now()
    exam.save(update_fields=['results_released', 'results_released_at'])
    posted = 0
    for session in ExamSession.objects.filter(exam=exam, status='submitted').select_related(
            'exam', 'exam__school', 'exam__subject', 'student'):
        post_grade(session)
        posted += 1
    return posted
