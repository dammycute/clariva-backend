from rest_framework import serializers, viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone
from .models import Grade
from apps.mixins import SchoolFilterMixin

class GradeSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = Grade
        fields = '__all__'
        read_only_fields = ('school', 'results_status', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at')

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None


class GradeViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Grade.objects.select_related('student', 'subject').all()
    serializer_class = GradeSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if user.role == 'student':
            return qs.filter(student=user)

        if user.role == 'teacher':
            from apps.exams.models import Subject
            try:
                teacher_subjects = set(Subject.objects.filter(teacher=user).values_list('id', flat=True))
                form_class_ygs = user.class_set.exclude(year_group=None).values_list('year_group', flat=True)
                for yg in form_class_ygs:
                    teacher_subjects.update(
                        Subject.objects.filter(year_group=yg).values_list('id', flat=True)
                    )
                qs = qs.filter(subject_id__in=teacher_subjects)
            except AttributeError:
                pass

        student_id = self.request.query_params.get('student_id')
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs

    @action(detail=False, methods=['post'])
    def submit_class(self, request):
        class_id = request.data.get('class_id')
        term = request.data.get('term')
        academic_year = request.data.get('academic_year')
        subject_id = request.data.get('subject_id')
        if not all([class_id, term, academic_year, subject_id]):
            return Response({'error': 'class_id, term, academic_year, subject_id required'}, status=400)
        if request.user.role not in ('teacher', 'principal', 'school_admin', 'super_admin'):
            return Response({'error': 'Only staff can submit grades'}, status=403)
        updated = Grade.objects.filter(
            student__class_group_id=class_id, term=term,
            academic_year=academic_year, subject_id=subject_id,
            school=request.user.school,
        ).exclude(results_status='approved').update(
            results_status='submitted',
            submitted_by=request.user,
            submitted_at=timezone.now(),
        )
        return Response({'submitted': updated})

    @action(detail=False, methods=['post'])
    def approve_class(self, request):
        class_id = request.data.get('class_id')
        term = request.data.get('term')
        academic_year = request.data.get('academic_year')
        subject_id = request.data.get('subject_id')
        if not all([class_id, term, academic_year, subject_id]):
            return Response({'error': 'class_id, term, academic_year, subject_id required'}, status=400)
        if request.user.role not in ('principal', 'school_admin', 'super_admin'):
            return Response({'error': 'Only principals or admins can approve grades'}, status=403)
        updated = Grade.objects.filter(
            student__class_group_id=class_id, term=term,
            academic_year=academic_year, subject_id=subject_id,
            school=request.user.school, results_status='submitted',
        ).update(
            results_status='approved',
            approved_by=request.user,
            approved_at=timezone.now(),
        )
        return Response({'approved': updated})

    @action(detail=False, methods=['post'])
    def reject_class(self, request):
        class_id = request.data.get('class_id')
        term = request.data.get('term')
        academic_year = request.data.get('academic_year')
        subject_id = request.data.get('subject_id')
        note = request.data.get('note', '')
        if not all([class_id, term, academic_year, subject_id]):
            return Response({'error': 'class_id, term, academic_year, subject_id required'}, status=400)
        updated = Grade.objects.filter(
            student__class_group_id=class_id, term=term,
            academic_year=academic_year, subject_id=subject_id,
            school=request.user.school, results_status='submitted',
        ).update(
            results_status='rejected',
            rejection_note=note,
        )
        return Response({'rejected': updated})
