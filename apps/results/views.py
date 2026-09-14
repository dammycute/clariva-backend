from decimal import Decimal

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils import timezone

from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User
from apps.exams.models import ReportCard
from .serializers import ReportCardSerializer


class ReportCardViewSet(SchoolFilterMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ReportCard.objects.select_related('student', 'student__student_profile__class_group').all()
    serializer_class = ReportCardSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if user.role in ('parent', 'guardian', 'student'):
            qs = qs.filter(is_released=True)

        student_id = self.request.query_params.get('student_id')
        class_id = self.request.query_params.get('class_id')
        term = self.request.query_params.get('term')
        academic_year = self.request.query_params.get('academic_year')
        if student_id:
            qs = qs.filter(student_id=student_id)
        if class_id:
            qs = qs.filter(student__student_profile__class_group_id=class_id)
        if term:
            qs = qs.filter(term=term)
        if academic_year:
            qs = qs.filter(academic_year=academic_year)
        return qs

    @action(detail=True, methods=['post'])
    def release(self, request, pk=None):
        card = self.get_object()
        card.is_released = True
        card.released_at = timezone.now()
        card.released_by = request.user
        card.save()
        return Response({'status': 'released'})

    @action(detail=True, methods=['post'])
    def unrelease(self, request, pk=None):
        card = self.get_object()
        card.is_released = False
        card.released_at = None
        card.released_by = None
        card.save()
        return Response({'status': 'unreleased'})

    @action(detail=False, methods=['post'])
    def generate(self, request):
        from apps.grades.models import Grade

        class_id = request.data.get('class_id')
        term = request.data.get('term')
        academic_year = request.data.get('academic_year')

        if not all([class_id, term, academic_year]):
            return Response({'error': 'class_id, term, and academic_year required'}, status=400)

        students = User.objects.filter(
            role='student', student_profile__class_group_id=class_id,
            student_profile__student_status='active', school=request.user.school
        )
        if not students:
            return Response({'error': 'No active students in this class'}, status=400)

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

        from apps.schools.models import GradingConfig
        try:
            gc = GradingConfig.objects.get(school=request.user.school)
            max_per_subject = gc.total_possible
        except GradingConfig.DoesNotExist:
            max_per_subject = 200

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
                skipped.append(student.get_full_name())
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
                    'scores': {
                        'ca1': float(g.ca1) if g.ca1 else 0,
                        'ca2': float(g.ca2) if g.ca2 else 0,
                        'assignment': float(g.assignment) if g.assignment else 0,
                        'exam': float(g.exam) if g.exam else 0,
                    },
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

        all_cards = ReportCard.objects.filter(
            term=term, academic_year=academic_year,
            student__student_profile__class_group_id=class_id,
        ).order_by('-average')

        for idx, card in enumerate(all_cards, 1):
            if card.average is not None:
                ReportCard.objects.filter(pk=card.pk).update(class_rank=idx)

        return Response({'generated': len(generated), 'skipped': skipped})
