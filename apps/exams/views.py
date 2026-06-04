import io
import random
import hashlib
import zipfile
from xml.etree import ElementTree
from datetime import timedelta
from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser
from django.db import transaction
from django.db.models import Avg, Sum, Count, Q
from django.http import FileResponse
from django.utils import timezone
from decimal import Decimal
from apps.mixins import SchoolFilterMixin
from .models import (
    Subject, StudentSubject, TimeTable, TimeSlot, ReportCard,
    Exam, Question, ExamSession,
)
from .parsers import parse_question_docx

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


# ─── Subjects ────────────────────────────────────────────────────

class SubjectSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = '__all__'
        read_only_fields = ('school',)

    def get_class_name(self, obj):
        return obj.year_group or 'All'

    def get_teacher_name(self, obj):
        return obj.teacher.full_name if obj.teacher else None


class SubjectViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        year_group = self.request.query_params.get('year_group')
        teacher_id = self.request.query_params.get('teacher_id')

        if teacher_id == 'me' and user.role == 'teacher':
            staff = user.staff_set.first()
            if staff:
                qs = qs.filter(teacher=staff)
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
        return obj.student.full_name if obj.student else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None


class StudentSubjectViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = StudentSubject.objects.select_related('student', 'subject').all()
    serializer_class = StudentSubjectSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        student_id = self.request.query_params.get('student_id')
        subject_id = self.request.query_params.get('subject_id')
        if student_id:
            qs = qs.filter(student_id=student_id)
        if subject_id:
            qs = qs.filter(subject_id=subject_id)
        return qs


# ─── Timetable ───────────────────────────────────────────────────

class TimeSlotSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()

    class Meta:
        model = TimeSlot
        fields = '__all__'
        read_only_fields = ('timetable',)

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None

    def get_teacher_name(self, obj):
        return obj.teacher.full_name if obj.teacher else None


class TimeTableSerializer(serializers.ModelSerializer):
    slots = TimeSlotSerializer(many=True, required=False)
    class_name = serializers.SerializerMethodField()

    class Meta:
        model = TimeTable
        fields = '__all__'
        read_only_fields = ('school',)

    def get_class_name(self, obj):
        return obj.class_group.name if obj.class_group else None

    def validate_slots(self, slots):
        """Clash detection: no teacher double-booked in same day+period."""
        if not slots:
            return slots
        teacher_periods = {}
        for slot in slots:
            teacher_id = slot.get('teacher')
            if not teacher_id:
                continue
            key = (slot['day'], slot['period'], teacher_id)
            if key in teacher_periods:
                raise serializers.ValidationError(
                    f'Teacher clashes on day {slot["day"]} period {slot["period"]}.'
                )
            teacher_periods[key] = True
        return slots

    def create(self, validated_data):
        slots_data = validated_data.pop('slots', [])
        tt = TimeTable.objects.create(**validated_data)
        for slot_data in slots_data:
            TimeSlot.objects.create(timetable=tt, **slot_data)
        return tt

    def update(self, instance, validated_data):
        slots_data = validated_data.pop('slots', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if slots_data is not None:
            instance.slots.all().delete()
            for slot_data in slots_data:
                TimeSlot.objects.create(timetable=instance, **slot_data)
        return instance

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['slots'] = TimeSlotSerializer(instance.slots.all(), many=True).data
        return rep


class TimeTableViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = TimeTable.objects.prefetch_related('slots').all()
    serializer_class = TimeTableSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        class_id = self.request.query_params.get('class_id')
        term = self.request.query_params.get('term')
        if class_id:
            qs = qs.filter(class_group_id=class_id)
        if term:
            qs = qs.filter(term=term)
        return qs

    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        tt = self.get_object()
        tt.is_published = True
        tt.save()
        return Response({'status': 'published'})

    @action(detail=True, methods=['post'])
    def unpublish(self, request, pk=None):
        tt = self.get_object()
        tt.is_published = False
        tt.save()
        return Response({'status': 'unpublished'})


# ─── Report Card ─────────────────────────────────────────────────

class ReportCardSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()

    class Meta:
        model = ReportCard
        fields = '__all__'
        read_only_fields = ('school',)

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else None

    def get_class_name(self, obj):
        return obj.student.class_group.name if obj.student and obj.student.class_group else None


class ReportCardViewSet(SchoolFilterMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ReportCard.objects.select_related('student', 'student__class_group').all()
    serializer_class = ReportCardSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        student_id = self.request.query_params.get('student_id')
        class_id = self.request.query_params.get('class_id')
        term = self.request.query_params.get('term')
        academic_year = self.request.query_params.get('academic_year')
        if student_id:
            qs = qs.filter(student_id=student_id)
        if class_id:
            qs = qs.filter(student__class_group_id=class_id)
        if term:
            qs = qs.filter(term=term)
        if academic_year:
            qs = qs.filter(academic_year=academic_year)
        return qs

    @action(detail=False, methods=['post'])
    def generate(self, request):
        """Generate report cards for a class + term. Creates or updates ReportCard records."""
        from apps.grades.models import Grade
        from apps.students.models import Student

        class_id = request.data.get('class_id')
        term = request.data.get('term')
        academic_year = request.data.get('academic_year')

        if not all([class_id, term, academic_year]):
            return Response({'error': 'class_id, term, and academic_year required'}, status=400)

        students = Student.objects.filter(class_group_id=class_id, status='active', school=request.user.school)
        if not students:
            return Response({'error': 'No active students in this class'}, status=400)

        # Get the year_group for this class
        from apps.classes.models import Class
        try:
            cls = Class.objects.get(pk=class_id)
            year_group = cls.year_group
        except Class.DoesNotExist:
            year_group = None

        if not year_group:
            return Response(
                {'error': 'This class has no year group assigned. Set the year group on the class before generating report cards.'},
                status=400,
            )

        # Get grading config for max possible per subject
        from apps.schools.models import GradingConfig
        try:
            gc = GradingConfig.objects.get(school=request.user.school)
            max_per_subject = gc.max_ca1 + gc.max_ca2 + gc.max_assignment + gc.max_exam
        except GradingConfig.DoesNotExist:
            max_per_subject = 200

        # Fetch valid subject IDs for this year group
        from apps.exams.models import Subject
        valid_subject_ids = Subject.objects.filter(
            school=request.user.school,
            year_group=year_group,
        ).values_list('id', flat=True)

        if not valid_subject_ids:
            return Response(
                {'error': f'No subjects found for year group {year_group}. Add subjects before generating report cards.'},
                status=400,
            )

        generated = []
        skipped = []
        for student in students:
            grades = Grade.objects.filter(
                student=student, term=term, academic_year=academic_year,
                school=request.user.school,
                subject_id__in=valid_subject_ids,
            ).select_related('subject')

            if not grades:
                skipped.append(student.full_name)
                continue

            grade_list = []
            total = Decimal('0')
            count = 0
            for g in grades:
                if g.total is not None:
                    total += g.total
                    count += 1
                grade_list.append({
                    'subject': g.subject.name if g.subject else 'Unknown',
                    'ca1': float(g.ca1) if g.ca1 else None,
                    'ca2': float(g.ca2) if g.ca2 else None,
                    'assignment': float(g.assignment) if g.assignment else None,
                    'exam': float(g.exam) if g.exam else None,
                    'total': float(g.total) if g.total else None,
                    'grade': g.grade,
                })

            avg = (total / count).quantize(Decimal('0.01')) if count > 0 else None

            rc, _ = ReportCard.objects.update_or_create(
                school=request.user.school,
                student=student,
                term=term,
                academic_year=academic_year,
                defaults={
                    'grades': grade_list,
                    'total_score': total,
                    'total_possible': Decimal(str(count * max_per_subject)),
                    'average': avg,
                },
            )
            generated.append(rc.id)

        # Compute class ranks
        all_cards = ReportCard.objects.filter(
            term=term, academic_year=academic_year,
            student__class_group_id=class_id,
        ).order_by('-average')

        for idx, card in enumerate(all_cards, 1):
            if card.average is not None:
                ReportCard.objects.filter(pk=card.pk).update(class_rank=idx)

        return Response({'generated': len(generated), 'skipped': skipped})


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
            pStyle.text = 'Heading1'
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
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


# ─── Exam / CBT ──────────────────────────────────────────────────

class ExamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = '__all__'
        read_only_fields = ('school',)


class ExamViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Exam.objects.all()
    serializer_class = ExamSerializer

    @action(detail=True, methods=['post'])
    def start(self, request, pk=None):
        exam = self.get_object()

        if exam.status not in ('published', 'ongoing'):
            return Response(
                {'error': 'Exam is not available. Status must be published or ongoing.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        student = request.user.student_set.first()
        if not student:
            return Response(
                {'error': 'Only students can start an exam.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Check for existing submitted session
        existing = ExamSession.objects.filter(exam=exam, student=student).first()
        if existing and existing.status == 'submitted':
            return Response(
                {'error': 'You have already submitted this exam.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Reuse an active session if one exists (student refreshing)
        if existing and existing.status == 'active':
            session = existing
        else:
            session = ExamSession.objects.create(
                school=request.user.school,
                exam=exam,
                student=student,
                started_at=timezone.now(),
                status='active',
            )

            # Shuffle question order if enabled
            if exam.shuffle_questions:
                q_ids = [str(qid) for qid in Question.objects.filter(exam=exam).values_list('id', flat=True)]
                random.shuffle(q_ids)
                session.question_order = q_ids
                session.save()

        # Build time remaining
        time_remaining = exam.duration_mins * 60

        # Return questions without correct_answer
        questions_qs = Question.objects.filter(exam=exam)
        if session.question_order:
            # Preserve shuffled order
            order_map = {str(qid): i for i, qid in enumerate(session.question_order)}
            questions_qs = sorted(questions_qs, key=lambda q: order_map.get(str(q.id), 999))
        else:
            questions_qs = list(questions_qs)

        question_data = []
        for q in questions_qs:
            opts = q.options
            if exam.shuffle_options and opts:
                seed = str(session.id)
                rng = random.Random(seed)
                shuffled = opts[:]
                rng.shuffle(shuffled)
                opts = shuffled

            question_data.append({
                'id': str(q.id),
                'body': q.body,
                'question_type': q.question_type,
                'options': opts,
                'difficulty': q.difficulty,
                'mark': q.mark,
                'topic': q.topic,
                'image_url': q.image_url,
            })

        return Response({
            'session_id': str(session.id),
            'time_remaining': time_remaining,
            'questions': question_data,
        })

    @action(detail=True, methods=['get'])
    def questions(self, request, pk=None):
        exam = self.get_object()
        student = request.user.student_set.first()
        if not student:
            return Response({'error': 'Only students can access exam questions.'}, status=status.HTTP_403_FORBIDDEN)

        session = ExamSession.objects.filter(exam=exam, student=student, status='active').first()
        if not session:
            return Response({'error': 'No active session. Start the exam first.'}, status=status.HTTP_403_FORBIDDEN)

        questions_qs = Question.objects.filter(exam=exam)
        if session.question_order:
            order_map = {str(qid): i for i, qid in enumerate(session.question_order)}
            questions_qs = sorted(questions_qs, key=lambda q: order_map.get(str(q.id), 999))
        else:
            questions_qs = list(questions_qs)

        question_data = []
        for q in questions_qs:
            opts = q.options
            if exam.shuffle_options and opts:
                seed = str(session.id)
                rng = random.Random(seed)
                shuffled = opts[:]
                rng.shuffle(shuffled)
                opts = shuffled

            question_data.append({
                'id': str(q.id),
                'body': q.body,
                'question_type': q.question_type,
                'options': opts,
                'difficulty': q.difficulty,
                'mark': q.mark,
                'topic': q.topic,
                'image_url': q.image_url,
            })

        return Response({'questions': question_data})

    @action(detail=True, methods=['post'],
            parser_classes=[MultiPartParser, FormParser])
    def upload_questions(self, request, pk=None):
        exam = self.get_object()
        questions_file = request.FILES.get('questions_file')
        if not questions_file:
            return Response(
                {'error': 'No file provided. Use field name "questions_file".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate file extension
        if not questions_file.name.lower().endswith('.docx'):
            return Response(
                {'error': f'Invalid file type. Expected a .docx file, got "{questions_file.name}".'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate content type
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

        # Parse the DOCX
        try:
            result = parse_question_docx(questions_file)
        except ValueError as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        replace = request.query_params.get('replace', '').lower() == 'true'
        warnings = []
        errors = []

        if replace:
            exam.question_set.all().delete()

        created = 0
        for idx, qdata in enumerate(result['questions'], 1):
            if not qdata.get('topic'):
                warnings.append(
                    f'Question {idx} had no TOPIC set, defaulted to null'
                )
            try:
                Question.objects.create(
                    school=request.user.school,
                    exam=exam,
                    body=qdata['body'],
                    question_type=qdata['question_type'],
                    options=qdata.get('options'),
                    correct_answer=qdata.get('correct_answer', ''),
                    topic=qdata.get('topic'),
                    difficulty=qdata.get('difficulty', 'medium'),
                    mark=qdata.get('mark', 1),
                )
                created += 1
            except Exception as e:
                errors.append(f'Question {idx}: {str(e)}')

        return Response({
            'created': created,
            'replaced': replace,
            'errors': errors,
            'warnings': warnings,
        })

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
            ('4. For MCQ: list options as A., B., C., D. and provide ANSWER: with the letter.', False),
            ('5. For True/False: set ANSWER: True or ANSWER: False.', False),
            ('6. For Short Answer: any ANSWER: value that is not True/False.', False),
            ('7. DIFFICULTY: easy, medium, or hard (defaults to medium).', False),
            ('8. MARK: any positive integer (defaults to 1).', False),
            ('9. TOPIC: optional category label.', False),
            ('10. Save your file as .docx and upload it.', False),
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


class QuestionViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Question.objects.all()
    serializer_class = QuestionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        exam_id = self.request.query_params.get('exam')
        if exam_id:
            qs = qs.filter(exam_id=exam_id)
        return qs

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        data = serializer.data
        if request.user.role == 'student':
            data.pop('correct_answer', None)
        return Response(data)

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        serializer = self.get_serializer(qs, many=True)
        data = serializer.data
        if request.user.role == 'student':
            for item in data:
                item.pop('correct_answer', None)
        return Response(data)


class ExamSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamSession
        fields = '__all__'
        read_only_fields = ('school', 'score', 'total_marks', 'passed', 'started_at', 'late_submission')


class ExamSessionViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = ExamSession.objects.all()
    serializer_class = ExamSessionSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if user.role == 'student':
            student = user.student_set.first()
            if student:
                qs = qs.filter(student=student)
        return qs

    def create(self, request, *args, **kwargs):
        return Response(
            {'error': 'Sessions cannot be created directly. Use the start endpoint.'},
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        session = self.get_object()
        student = request.user.student_set.first()
        if not student or session.student != student:
            return Response(
                {'error': 'This session does not belong to you.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if session.status != 'active':
            return Response(
                {'error': 'Session is not active. It may have already been submitted.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        exam = session.exam
        now = timezone.now()

        # Time limit enforcement
        late = False
        if exam.time_limit_enforced and session.started_at:
            deadline = session.started_at + timedelta(minutes=exam.duration_mins) + timedelta(minutes=5)
            if now > deadline:
                late = True

        # Grade server-side
        questions = Question.objects.filter(exam=exam)
        answers = request.data.get('answers', {}) or {}
        score = 0
        for q in questions:
            user_answer = answers.get(str(q.id))
            if user_answer is None:
                continue
            if q.question_type in ('mcq', 'true_false'):
                if str(user_answer).strip() == str(q.correct_answer).strip():
                    score += q.mark
            else:
                if str(user_answer).strip().lower() == str(q.correct_answer).strip().lower():
                    score += q.mark

        total_marks = sum(q.mark for q in questions)
        passed = (score / total_marks * 100) >= exam.pass_mark if total_marks > 0 else False
        percentage = round((score / total_marks * 100), 2) if total_marks > 0 else 0

        session.score = score
        session.total_marks = total_marks
        session.passed = passed
        session.submitted_at = now
        session.status = 'submitted'
        session.late_submission = late
        session.answers = answers
        session.save()

        return Response({
            'score': float(score),
            'total_marks': float(total_marks),
            'passed': passed,
            'percentage': percentage,
            'late_submission': late,
        })
