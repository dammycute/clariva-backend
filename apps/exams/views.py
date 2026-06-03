from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Avg, Sum, Count, Q
from decimal import Decimal
from apps.mixins import SchoolFilterMixin
from .models import (
    Subject, StudentSubject, TimeTable, TimeSlot, ReportCard,
    Exam, Question, ExamSession,
)


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

        # Get grading config for max possible per subject
        from apps.schools.models import GradingConfig
        try:
            gc = GradingConfig.objects.get(school=request.user.school)
            max_per_subject = gc.max_ca1 + gc.max_ca2 + gc.max_assignment + gc.max_exam
        except GradingConfig.DoesNotExist:
            max_per_subject = 200

        generated = []
        for student in students:
            grades = Grade.objects.filter(
                student=student, term=term, academic_year=academic_year,
                school=request.user.school,
                subject__year_group=year_group,
            ).select_related('subject')

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

        return Response({'generated': len(generated)})


# ─── Exam / CBT (unchanged) ──────────────────────────────────────

class ExamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Exam
        fields = '__all__'
        read_only_fields = ('school',)


class ExamViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Exam.objects.all()
    serializer_class = ExamSerializer


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = '__all__'
        read_only_fields = ('school',)


class QuestionViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Question.objects.all()
    serializer_class = QuestionSerializer


class ExamSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExamSession
        fields = '__all__'
        read_only_fields = ('school',)


class ExamSessionViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = ExamSession.objects.all()
    serializer_class = ExamSessionSerializer
