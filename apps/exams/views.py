import io
import random
import hashlib
import zipfile
from xml.etree import ElementTree
from datetime import timedelta
from rest_framework import serializers, viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from django.db.models import Avg, Sum, Count, Q
from django.http import FileResponse
from django.utils import timezone
from decimal import Decimal
from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User
from apps.classes.models import Class
from . import cbt
from .models import (
    Subject, StudentSubject,
    Exam, Question, ExamSession, ExamAnswer,
)
from .parsers import parse_question_docx

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'

from apps.permissions import ADMIN_ROLES, STAFF_WRITE_ROLES

STAFF_ROLES = {'school_admin', 'admin_officer', 'principal', 'teacher', 'bursary', 'super_admin'}

class IsStaffOrReadOnly(permissions.IsAuthenticated):
    """Admins and teachers may write; everyone else is read-only. Teachers are limited to their own subjects in the views."""
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return getattr(request.user, 'role', None) in STAFF_WRITE_ROLES


# ─── Subjects ────────────────────────────────────────────────────

class SubjectSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()
    grading_mode_label = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = '__all__'
        read_only_fields = ('school',)

    def get_grading_mode_label(self, obj):
        return dict(Subject._meta.get_field('grading_mode').choices).get(obj.grading_mode, obj.grading_mode)

    def get_class_name(self, obj):
        return obj.year_group or 'All'

    def get_teacher_name(self, obj):
        return obj.teacher.get_full_name() if obj.teacher else None


class SubjectViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    write_roles = STAFF_WRITE_ROLES

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        year_group = self.request.query_params.get('year_group')
        teacher_id = self.request.query_params.get('teacher_id')

        if teacher_id == 'me' and user.role == 'teacher':
            if hasattr(user, 'teacher_profile'):
                qs = qs.filter(teacher=user)
        elif teacher_id:
            qs = qs.filter(teacher_id=teacher_id)

        if year_group:
            qs = qs.filter(year_group=year_group)
        return qs


# ─── Student Subject Enrollment ──────────────────────────────────

class StudentSubjectSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = StudentSubject
        fields = '__all__'
        read_only_fields = ('school',)

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None


class StudentSubjectViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = StudentSubject.objects.select_related('student', 'subject').all()
    serializer_class = StudentSubjectSerializer
    write_roles = STAFF_WRITE_ROLES

    def get_queryset(self):
        qs = super().get_queryset()
        student_id = self.request.query_params.get('student_id')
        subject_id = self.request.query_params.get('subject_id')
        if student_id:
            qs = qs.filter(student_id=student_id)
        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        return qs


# ─── DOCX helpers ─────────────────────────────────────────────────

def _make_docx_bytes(paragraphs: list[tuple[str, bool]]) -> bytes:
    """
    Build a minimal DOCX file in memory.
    Each tuple is (text, is_bold).
    """
    root = ElementTree.Element(f'{{{W_NS}}}document')
    body = ElementTree.SubElement(root, f'{{{W_NS}}}body')

    for text, bold in paragraphs:
        p = ElementTree.SubElement(body, f'{{{W_NS}}}p')
        pPr = ElementTree.SubElement(p, f'{{{W_NS}}}pPr')
        if bold:
            pStyle = ElementTree.SubElement(pPr, f'{{{W_NS}}}pStyle')
            pStyle.set(f'{{{W_NS}}}val', 'Heading1')
        r = ElementTree.SubElement(p, f'{{{W_NS}}}r')
        rPr = ElementTree.SubElement(r, f'{{{W_NS}}}rPr')
        if bold:
            b = ElementTree.SubElement(rPr, f'{{{W_NS}}}b')
        t = ElementTree.SubElement(r, f'{{{W_NS}}}t')
        t.text = text

    xml_bytes = ElementTree.tostring(root, xml_declaration=True, encoding='UTF-8')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _CONTENT_TYPES)
        zf.writestr('_rels/.rels', _RELS)
        zf.writestr('word/_rels/document.xml.rels', _DOC_RELS)
        zf.writestr('word/document.xml', xml_bytes)
    return buf.getvalue()


_CONTENT_TYPES = b"""\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = b"""\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = b"""\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""


# ─── Exam / CBT ──────────────────────────────────────────────────

GRADED_COMPONENTS = ('ca1', 'ca2', 'assignment', 'exam')


def _manages_subject(user, subject) -> bool:
    """Admins manage every subject. A teacher manages only the subjects they teach."""
    if user.role in ADMIN_ROLES:
        return True
    return user.role == 'teacher' and subject is not None and subject.teacher_id == user.id


def _check_can_manage(user, exam):
    """Raise unless this user may change this exam."""
    if user.role != 'super_admin' and exam.school_id != user.school_id:
        raise PermissionDenied('This exam belongs to another school.')
    if not _manages_subject(user, exam.subject):
        raise PermissionDenied('You can only change exams for the subjects you teach.')


def _ensure_no_attempts(exam):
    """Questions are the marking key. Once a student has started, they stay as they are."""
    if ExamSession.objects.filter(exam=exam).exists():
        raise ValidationError({
            'error': 'Students have already started this exam, so questions cannot be added or removed. '
                     'Duplicate the exam to make a changed copy.'
        })


class ExamSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()
    class_names = serializers.SerializerMethodField()
    classes = serializers.PrimaryKeyRelatedField(many=True, queryset=Class.objects.all(), required=False)
    question_count = serializers.SerializerMethodField()
    total_marks = serializers.SerializerMethodField()
    is_open = serializers.SerializerMethodField()
    my_status = serializers.SerializerMethodField()
    my_result = serializers.SerializerMethodField()

    class Meta:
        model = Exam
        fields = '__all__'
        read_only_fields = ('school', 'results_released', 'results_released_at', 'closed_at')

    # -- computed fields --
    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None

    def _class_list(self, obj):
        classes = list(obj.classes.all())
        if not classes and obj.class_group:
            classes = [obj.class_group]
        return classes

    def get_class_names(self, obj):
        return [c.name for c in self._class_list(obj)]

    def get_class_name(self, obj):
        names = self.get_class_names(obj)
        return ', '.join(names) if names else None

    def get_question_count(self, obj):
        annotated = getattr(obj, 'n_questions', None)
        return annotated if annotated is not None else obj.question_set.count()

    def get_total_marks(self, obj):
        annotated = getattr(obj, 'n_marks', None)
        if annotated is not None:
            return annotated
        return obj.question_set.aggregate(total=Sum('mark'))['total'] or 0

    def get_is_open(self, obj):
        return cbt.exam_is_open(obj)

    def get_my_status(self, obj):
        """For a student: not_started, in_progress or submitted."""
        mine = self.context.get('my_sessions')
        if mine is None:
            return None
        status_ = mine.get(obj.id)
        return {'active': 'in_progress', 'submitted': 'submitted'}.get(status_, 'not_started')

    def get_my_result(self, obj):
        results = self.context.get('my_results')
        return results.get(obj.id) if results is not None else None

    # -- checks --
    def validate_status(self, value):
        value = {'ongoing': 'published', 'completed': 'closed'}.get(value, value)
        if value not in Exam.STATUS_CHOICES:
            raise serializers.ValidationError('Status must be draft, published, closed or archived.')
        return value

    def validate_duration_mins(self, value):
        if value is None or value < 1:
            raise serializers.ValidationError('Duration must be at least 1 minute.')
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        instance = self.instance

        classes = attrs.get('classes')
        for c in classes or []:
            if c.school_id != user.school_id:
                raise serializers.ValidationError({'classes': 'Choose classes from your own school.'})
        subject = attrs.get('subject')
        if subject is not None and subject.school_id != user.school_id:
            raise serializers.ValidationError({'subject': 'Choose a subject from your own school.'})

        start = attrs.get('start_time', getattr(instance, 'start_time', None))
        end = attrs.get('end_time', getattr(instance, 'end_time', None))
        if start and end and end <= start:
            raise serializers.ValidationError({'end_time': 'The end time must be after the start time.'})

        new_status = attrs.get('status', instance.status if instance else 'draft')
        publishing = new_status == 'published' and (instance is None or instance.status != 'published')
        if publishing:
            if instance is None:
                raise serializers.ValidationError({'status': 'Add questions first. Save the exam as a draft, then publish.'})
            if not Question.objects.filter(exam=instance).exists():
                raise serializers.ValidationError({'status': 'Add at least one question before publishing.'})
            class_list = classes if classes is not None else list(instance.classes.all())
            if not class_list and not instance.class_group_id and not attrs.get('class_group'):
                raise serializers.ValidationError({'classes': 'Choose which classes this exam is for before publishing.'})
        return attrs

    def _sync_legacy_class(self, instance, validated):
        """Keep the older single class field pointing at the first chosen class."""
        if 'classes' in validated:
            first = instance.classes.order_by('name').first()
            if instance.class_group_id != (first.pk if first else None):
                instance.class_group = first
                instance.save(update_fields=['class_group'])

    def create(self, validated_data):
        if 'release_mode' not in validated_data and validated_data.get('component') in GRADED_COMPONENTS:
            validated_data['release_mode'] = 'on_release'
        instance = super().create(validated_data)
        self._sync_legacy_class(instance, validated_data)
        return instance

    def update(self, instance, validated_data):
        instance = super().update(instance, validated_data)
        self._sync_legacy_class(instance, validated_data)
        return instance


def _question_payload(exam, session):
    """Questions as a student sees them: no answer key, in this attempt's order."""
    questions = list(Question.objects.filter(exam=exam).order_by('order', 'created_at'))
    if session.question_order:
        order_map = {str(qid): i for i, qid in enumerate(session.question_order)}
        questions.sort(key=lambda q: order_map.get(str(q.id), 999))
    data = []
    for q in questions:
        opts = q.options
        if exam.shuffle_options and opts:
            shuffled = opts[:]
            random.Random(str(session.id)).shuffle(shuffled)
            opts = shuffled
        data.append({
            'id': str(q.id),
            'body': q.body,
            'question_type': q.question_type,
            'options': opts,
            'difficulty': q.difficulty,
            'mark': q.mark,
            'topic': q.topic,
            'image_url': q.image_url,
        })
    return data


def _saved_answers(session):
    return {str(a.question_id): a.answer for a in session.saved_answers.all()}


def _result_payload(session):
    """What a student is told after submitting. Scores stay hidden while results are held."""
    exam = session.exam
    base = {'submitted': True, 'late_submission': session.late_submission, 'auto_submitted': session.auto_submitted}
    if not cbt.results_visible(exam):
        return {**base, 'held': True,
                'message': 'Your answers are saved. Your teacher will release the results.'}
    total = session.total_marks or 0
    return {**base, 'held': False,
            'score': float(session.score or 0), 'total_marks': float(total),
            'passed': bool(session.passed),
            'percentage': round((session.score or 0) / total * 100) if total else 0}


class ExamViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Exam.objects.all()
    serializer_class = ExamSerializer

    WRITE_ACTIONS = {'create', 'update', 'partial_update', 'destroy', 'upload_questions',
                     'question_template', 'duplicate', 'close', 'release', 'copy_questions'}

    def get_permissions(self):
        if self.action in self.WRITE_ACTIONS:
            return [IsStaffOrReadOnly()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        qs = (qs.select_related('subject', 'class_group')
                .prefetch_related('classes')
                .annotate(n_questions=Count('question', distinct=True),
                          n_marks=Sum('question__mark')))

        if user.role == 'teacher':
            subject_ids = Subject.objects.filter(teacher=user).values_list('id', flat=True)
            qs = qs.filter(subject_id__in=subject_ids)
        elif user.role == 'student':
            # Students see only published or closed exams made for their class.
            candidates = qs.filter(status__in=('published', 'closed'))
            ids = [e.id for e in candidates if cbt.student_may_sit(e, user)]
            qs = qs.filter(id__in=ids)
        elif user.role in ('parent',):
            return qs.none()

        params = self.request.query_params
        if params.get('status'):
            qs = qs.filter(status=params['status'])
        if params.get('subject'):
            qs = qs.filter(subject_id=params['subject'])
        return qs.order_by('-created_at')

    def get_serializer_context(self):
        ctx = super().get_serializer_context()
        user = self.request.user
        if user.is_authenticated and user.role == 'student':
            mine = list(ExamSession.objects.filter(student=user).select_related('exam'))
            ctx['my_sessions'] = {s.exam_id: s.status for s in mine}
            # A student's own score, only once results are visible for that exam.
            ctx['my_results'] = {
                s.exam_id: {'score': s.score, 'total_marks': s.total_marks, 'passed': s.passed}
                for s in mine if s.status == 'submitted' and cbt.results_visible(s.exam)
            }
        return ctx

    # -- who may change what --
    def perform_create(self, serializer):
        user = self.request.user
        subject = serializer.validated_data.get('subject')
        if user.role == 'teacher' and not _manages_subject(user, subject):
            raise PermissionDenied('Choose one of the subjects you teach.')
        return super().perform_create(serializer)

    def perform_update(self, serializer):
        user = self.request.user
        _check_can_manage(user, serializer.instance)
        new_subject = serializer.validated_data.get('subject')
        if new_subject is not None and not _manages_subject(user, new_subject):
            raise PermissionDenied('Choose one of the subjects you teach.')
        return super().perform_update(serializer)

    def perform_destroy(self, instance):
        _check_can_manage(self.request.user, instance)
        if ExamSession.objects.filter(exam=instance).exists():
            raise ValidationError({'error': 'Students have taken this exam. Archive it instead of deleting it.'})
        return super().perform_destroy(instance)

    # -- student: start or resume --
    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        exam = self.get_object()
        student = request.user

        if student.role != 'student':
            return Response({'error': 'Only students can start an exam.'}, status=status.HTTP_403_FORBIDDEN)
        if not cbt.student_may_sit(exam, student):
            return Response({'error': 'This exam is not for your class.'}, status=status.HTTP_403_FORBIDDEN)
        if exam.status != 'published':
            return Response({'error': 'Exam is not available. It must be published.'},
                            status=status.HTTP_403_FORBIDDEN)

        now = timezone.now()
        if exam.start_time and now < exam.start_time:
            return Response(
                {'error': f'This exam has not started yet. It opens at {exam.start_time.strftime("%d %b %Y %H:%M")}.'},
                status=status.HTTP_403_FORBIDDEN)

        # Finish any attempt of this student that ran out of time.
        cbt.close_overdue_sessions(exam=exam, student=student)

        existing = ExamSession.objects.filter(exam=exam, student=student).first()
        if existing is None and exam.end_time and now > exam.end_time:
            return Response({'error': 'The exam window has closed.'}, status=status.HTTP_403_FORBIDDEN)

        # get_or_create keeps a double click from making two attempts.
        session, created = ExamSession.objects.get_or_create(
            exam=exam, student=student,
            defaults={'school': student.school, 'started_at': now, 'status': 'active',
                      'deadline': cbt.attempt_deadline(exam, now)},
        )
        if session.status == 'submitted':
            message = ('Your time ran out and your answers were submitted.' if session.auto_submitted
                       else 'You have already submitted this exam.')
            return Response({'error': message, 'already_submitted': True}, status=status.HTTP_403_FORBIDDEN)

        if created and exam.shuffle_questions:
            q_ids = [str(qid) for qid in Question.objects.filter(exam=exam).values_list('id', flat=True)]
            random.shuffle(q_ids)
            session.question_order = q_ids
            session.save(update_fields=['question_order'])

        return Response({
            'session_id': str(session.id),
            'time_remaining': cbt.seconds_left(session, now if created else None),
            'questions': _question_payload(exam, session),
            'saved_answers': _saved_answers(session),
        })

    @action(detail=True, methods=['get'])
    def questions(self, request, pk=None):
        exam = self.get_object()
        if request.user.role != 'student':
            return Response({'error': 'Only students can access exam questions.'}, status=status.HTTP_403_FORBIDDEN)
        session = ExamSession.objects.filter(exam=exam, student=request.user, status='active').first()
        if not session:
            return Response({'error': 'No active session. Start the exam first.'}, status=status.HTTP_403_FORBIDDEN)
        return Response({'questions': _question_payload(exam, session), 'saved_answers': _saved_answers(session)})

    # -- staff: copy, close, release --
    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        """Clone an exam and all its questions into a new draft."""
        original = self.get_object()
        _check_can_manage(request.user, original)

        new_exam = Exam.objects.create(
            school=original.school,
            title=f'Copy of {original.title}',
            subject=original.subject,
            class_group=original.class_group,
            duration_mins=original.duration_mins,
            pass_mark=original.pass_mark,
            instructions=original.instructions,
            component=original.component,
            term=original.term,
            academic_year=original.academic_year,
            release_mode=original.release_mode,
            shuffle_questions=original.shuffle_questions,
            shuffle_options=original.shuffle_options,
            time_limit_enforced=original.time_limit_enforced,
            status='draft',
        )
        new_exam.classes.set(original.classes.all())
        for q in Question.objects.filter(exam=original):
            Question.objects.create(
                school=original.school, exam=new_exam, body=q.body, image_url=q.image_url,
                question_type=q.question_type, options=q.options, correct_answer=q.correct_answer,
                accepted_answers=q.accepted_answers, topic=q.topic, difficulty=q.difficulty,
                mark=q.mark, order=q.order,
            )
        return Response(self.get_serializer(new_exam).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def copy_questions(self, request, pk=None):
        """Copy questions from another exam in this school into this exam."""
        target = self.get_object()
        _check_can_manage(request.user, target)
        _ensure_no_attempts(target)
        source = self.get_queryset().filter(pk=request.data.get('source_exam')).first()
        if source is None:
            return Response({'error': 'Choose an exam to copy questions from.'}, status=status.HTTP_400_BAD_REQUEST)
        if source.pk == target.pk:
            return Response({'error': 'Choose a different exam.'}, status=status.HTTP_400_BAD_REQUEST)
        questions = Question.objects.filter(exam=source)
        wanted = request.data.get('question_ids')
        if wanted:
            questions = questions.filter(id__in=wanted)
        start_order = Question.objects.filter(exam=target).count()
        created = 0
        for i, q in enumerate(questions.order_by('order', 'created_at'), start=1):
            Question.objects.create(
                school=target.school, exam=target, body=q.body, image_url=q.image_url,
                question_type=q.question_type, options=q.options, correct_answer=q.correct_answer,
                accepted_answers=q.accepted_answers, topic=q.topic, difficulty=q.difficulty,
                mark=q.mark, order=start_order + i,
            )
            created += 1
        return Response({'created': created})

    @action(detail=True, methods=['post'])
    def close(self, request, pk=None):
        """Close the exam now and submit every attempt that is still running."""
        exam = self.get_object()
        _check_can_manage(request.user, exam)
        submitted = cbt.close_exam(exam)
        return Response({'status': exam.status, 'attempts_submitted': submitted})

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        """Let students see their scores, and write the grades."""
        exam = self.get_object()
        _check_can_manage(request.user, exam)
        if ExamSession.objects.filter(exam=exam, status='active').exists():
            cbt.close_overdue_sessions(exam=exam)
        posted = cbt.release_results(exam)
        return Response({'results_released': True, 'grades_posted': posted})

    # -- upload / template --
    @action(detail=True, methods=['post'],
            parser_classes=[MultiPartParser, FormParser])
    def upload_questions(self, request, pk=None):
        exam = self.get_object()
        _check_can_manage(request.user, exam)
        _ensure_no_attempts(exam)
        questions_file = request.FILES.get('questions_file')
        if not questions_file:
            return Response(
                {'error': 'No file provided. Use field name "questions_file".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not questions_file.name.lower().endswith('.docx'):
            return Response(
                {'error': f'Invalid file type. Expected a .docx file, got "{questions_file.name}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        ctype = questions_file.content_type or ''
        allowed_ctypes = (
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/octet-stream',
        )
        if ctype and ctype not in allowed_ctypes:
            return Response(
                {'error': f'Invalid content type "{ctype}". Expected application/vnd.openxmlformats-officedocument.wordprocessingml.document.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            result = parse_question_docx(questions_file)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        replace = request.query_params.get('replace', '').lower() == 'true'
        warnings = []
        errors = []

        if replace:
            exam.question_set.all().delete()

        created = 0
        for idx, qdata in enumerate(result['questions'], 1):
            if not qdata.get('topic'):
                warnings.append(f'Question {idx} had no TOPIC set, defaulted to null')
            try:
                Question.objects.create(
                    school=request.user.school,
                    exam=exam,
                    body=qdata['body'],
                    question_type=qdata['question_type'],
                    options=qdata.get('options'),
                    correct_answer=qdata.get('correct_answer', ''),
                    accepted_answers=qdata.get('accepted_answers'),
                    topic=qdata.get('topic'),
                    difficulty=qdata.get('difficulty', 'medium'),
                    mark=qdata.get('mark', 1),
                )
                created += 1
            except Exception as e:
                errors.append(f'Question {idx}: {str(e)}')

        return Response({'created': created, 'replaced': replace, 'errors': errors, 'warnings': warnings})

    @action(detail=False, methods=['get'])
    def question_template(self, request):
        paragraphs = [
            ('Clariva CBT Exam Template', True),
            ('', False),
            ('EXAM: Mid-Term Examination', False),
            ('SUBJECT: Mathematics', False),
            ('CLASS: SS1', False),
            ('DURATION: 60', False),
            ('PASS_MARK: 40', False),
            ('INSTRUCTIONS: Answer all questions. Each question carries the mark indicated.', False),
            ('', False),
            ('---', False),
            ('', False),
            ('Q1. What is the capital of Nigeria?', False),
            ('A. Lagos', False),
            ('B. Abuja', False),
            ('C. Port Harcourt', False),
            ('D. Kano', False),
            ('ANSWER: B', False),
            ('DIFFICULTY: easy', False),
            ('MARK: 2', False),
            ('TOPIC: Geography', False),
            ('', False),
            ('---', False),
            ('', False),
            ('Q2. The earth revolves around the sun.', False),
            ('ANSWER: True', False),
            ('DIFFICULTY: easy', False),
            ('MARK: 1', False),
            ('TOPIC: Science', False),
            ('', False),
            ('---', False),
            ('', False),
            ('Q3. Name the largest planet in our solar system.', False),
            ('ANSWER: Jupiter', False),
            ('ACCEPT: The planet Jupiter | Jupiter planet', False),
            ('DIFFICULTY: medium', False),
            ('MARK: 2', False),
            ('TOPIC: Astronomy', False),
            ('', False),
            ('---', False),
            ('', False),
            ('TIPS & RULES', True),
            ('', False),
            ('1. The header block (EXAM, SUBJECT, CLASS, DURATION, PASS_MARK, INSTRUCTIONS) is optional.', False),
            ('2. Separate questions using --- (three dashes) on their own line.', False),
            ('3. Each question must start with Q1., Q2., Q3., etc.', False),
            ('4. For MCQ: list options as A., B., C., D. and set ANSWER: to the letter (A/B/C/D). It is resolved to the option text automatically.', False),
            ('5. For True/False: set ANSWER: True or ANSWER: False.', False),
            ('6. For Short Answer: any ANSWER: value that is not True/False.', False),
            ('7. Short answer only: ACCEPT: lists other answers that are also right, separated by |.', False),
            ('8. Numbers match as numbers, so 1540 and 1,540 are the same answer.', False),
            ('9. DIFFICULTY: easy, medium, or hard (defaults to medium).', False),
            ('10. MARK: any positive integer (defaults to 1).', False),
            ('11. TOPIC: optional category label.', False),
            ('12. Save your file as .docx and upload it.', False),
        ]
        docx_bytes = _make_docx_bytes(paragraphs)
        return FileResponse(
            io.BytesIO(docx_bytes),
            as_attachment=True,
            filename='cbt_question_template.docx',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = '__all__'
        read_only_fields = ('school',)

    def validate(self, attrs):
        qtype = attrs.get('question_type', getattr(self.instance, 'question_type', None))
        options = attrs.get('options', getattr(self.instance, 'options', None))
        if qtype == 'mcq' and (not options or len([o for o in options if str(o).strip()]) < 2):
            raise serializers.ValidationError({'options': 'A multiple choice question needs at least two options.'})
        accepted = attrs.get('accepted_answers')
        if accepted is not None and not (isinstance(accepted, list) and all(isinstance(a, str) for a in accepted)):
            raise serializers.ValidationError({'accepted_answers': 'Give a list of answers.'})
        return attrs


class QuestionViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Question.objects.all().order_by('order', 'created_at')
    serializer_class = QuestionSerializer

    def get_permissions(self):
        if self.action in {'create', 'update', 'partial_update', 'destroy'}:
            return [IsStaffOrReadOnly()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role in ('student', 'parent'):
            return qs.none()  # answer keys must not reach students
        if user.role == 'teacher':
            qs = qs.filter(exam__subject__teacher=user)
        exam_id = self.request.query_params.get('exam')
        if exam_id:
            qs = qs.filter(exam_id=exam_id)
        return qs

    def perform_create(self, serializer):
        exam = serializer.validated_data.get('exam')
        if exam is None:
            raise ValidationError({'exam': 'Choose the exam this question belongs to.'})
        _check_can_manage(self.request.user, exam)
        _ensure_no_attempts(exam)
        return super().perform_create(serializer)

    def perform_update(self, serializer):
        user = self.request.user
        _check_can_manage(user, serializer.instance.exam)
        new_exam = serializer.validated_data.get('exam')
        if new_exam is not None and new_exam.pk != serializer.instance.exam_id:
            _check_can_manage(user, new_exam)
            _ensure_no_attempts(new_exam)
        return super().perform_update(serializer)

    def perform_destroy(self, instance):
        _check_can_manage(self.request.user, instance.exam)
        _ensure_no_attempts(instance.exam)
        return super().perform_destroy(instance)

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        return Response(self.get_serializer(instance).data)

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        return Response(self.get_serializer(qs, many=True).data)


class ExamSessionSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    result_visible = serializers.SerializerMethodField()

    class Meta:
        model = ExamSession
        fields = '__all__'
        read_only_fields = ('school', 'score', 'total_marks', 'passed', 'started_at', 'late_submission',
                            'deadline', 'last_saved_at', 'auto_submitted')

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student else None

    def get_result_visible(self, obj):
        return cbt.results_visible(obj.exam)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        user = self.context['request'].user
        if user.role == 'student':
            data.pop('session_code', None)
            if not cbt.results_visible(instance.exam):
                for key in ('score', 'total_marks', 'passed'):
                    data[key] = None
        return data


class ExamSessionViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = ExamSession.objects.select_related('student', 'exam').all()
    serializer_class = ExamSessionSerializer
    write_roles = STAFF_WRITE_ROLES
    http_method_names = ['get', 'post', 'delete', 'head', 'options']   # no editing of scores or answers

    def get_permissions(self):
        # Students save and submit their own attempt; every other write is staff only.
        if self.action in ('submit', 'save'):
            return [permissions.IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == 'student':
            return qs.filter(student=user)
        if user.role == 'parent':
            return qs.none()
        if user.role == 'teacher':
            qs = qs.filter(exam__subject__teacher=user)
        exam_id = self.request.query_params.get('exam_id') or self.request.query_params.get('exam')
        if exam_id:
            # Opening the results of an exam also closes attempts that ran out of time.
            cbt.close_overdue_sessions(exam_id=exam_id, school=user.school)
            qs = qs.filter(exam_id=exam_id)
        return qs

    def create(self, request, *args, **kwargs):
        return Response(
            {'error': 'Sessions cannot be created directly. Use the start endpoint.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    def _own_session(self, request):
        session = self.get_object()
        if request.user.role != 'student' or session.student != request.user:
            raise PermissionDenied('This session does not belong to you.')
        return session

    @action(detail=True, methods=['post'])
    def save(self, request, pk=None):
        """Save answers as the student types. Also tells the browser how much time is left."""
        session = self._own_session(request)
        if session.status != 'active':
            return Response({'closed': True, **_result_payload(session)})
        if cbt.is_overdue(session):
            session, _ = cbt.finalize_session(session.pk, reason='time')
            return Response({'closed': True, **_result_payload(session)})

        answers = request.data.get('answers') or {}
        if not isinstance(answers, dict):
            return Response({'error': 'answers must be an object of question id to answer.'},
                            status=status.HTTP_400_BAD_REQUEST)
        valid = {str(i) for i in Question.objects.filter(exam=session.exam).values_list('id', flat=True)}
        saved = 0
        with transaction.atomic():
            for qid, text in answers.items():
                if str(qid) in valid:
                    ExamAnswer.objects.update_or_create(
                        session=session, question_id=qid, defaults={'answer': str(text)[:5000]})
                    saved += 1
            session.last_saved_at = timezone.now()
            session.save(update_fields=['last_saved_at'])
        return Response({'closed': False, 'saved': saved, 'time_remaining': cbt.seconds_left(session)})

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        session = self._own_session(request)
        if session.status != 'active':
            return Response(_result_payload(session))      # sending Submit twice is harmless

        session.tab_switches = int(request.data.get('tab_switches', 0) or 0)
        session.save(update_fields=['tab_switches'])
        session, _ = cbt.finalize_session(session.pk, answers=request.data.get('answers'), reason='student')
        return Response(_result_payload(session))

    @action(detail=True, methods=['post'])
    def reset(self, request, pk=None):
        """Staff: remove one student's attempt so they can sit the exam again. It is logged."""
        session = self.get_object()
        _check_can_manage(request.user, session.exam)
        session.delete()
        return Response({'reset': True})
