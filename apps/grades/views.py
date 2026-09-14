from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import Grade
from .serializers import GradeSerializer
from .services import GradeService
from apps.mixins import SchoolFilterMixin


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
        try:
            result = GradeService.submit_class(request.user, class_id, subject_id, term, academic_year)
            return Response(result)
        except (PermissionDenied, ValidationError) as e:
            return Response({'error': str(e)}, status=getattr(e, 'status_code', 400))

    @action(detail=False, methods=['post'])
    def approve_class(self, request):
        class_id = request.data.get('class_id')
        term = request.data.get('term')
        academic_year = request.data.get('academic_year')
        subject_id = request.data.get('subject_id')
        try:
            result = GradeService.approve_class(request.user, class_id, subject_id, term, academic_year)
            return Response(result)
        except (PermissionDenied, ValidationError) as e:
            return Response({'error': str(e)}, status=getattr(e, 'status_code', 400))

    @action(detail=False, methods=['post'])
    def reject_class(self, request):
        class_id = request.data.get('class_id')
        term = request.data.get('term')
        academic_year = request.data.get('academic_year')
        subject_id = request.data.get('subject_id')
        note = request.data.get('note', '')
        try:
            result = GradeService.reject_class(request.user, class_id, subject_id, term, academic_year, note)
            return Response(result)
        except (PermissionDenied, ValidationError) as e:
            return Response({'error': str(e)}, status=getattr(e, 'status_code', 400))
