from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.grades.models import Grade
from .models import ReportCard

RELEASE_ROLES = {'principal', 'school_admin', 'super_admin'}


class ReportCardService:

    @staticmethod
    @transaction.atomic
    def generate_for_class(school, class_id, term, academic_year):
        students = User.objects.filter(
            school=school,
            role='student',
            student_profile__class_group_id=class_id,
            student_profile__student_status='active',
        )
        generated = 0
        for student in students:
            grades = Grade.objects.filter(
                student=student,
                term=term,
                academic_year=academic_year,
                school=school,
                results_status='approved',
            ).select_related('subject')

            if not grades.exists():
                continue

            grade_snapshot = [
                {
                    'subject': g.subject.name,
                    'subject_id': str(g.subject_id),
                    'scores': {
                        'ca1': float(g.ca1) if g.ca1 else 0,
                        'ca2': float(g.ca2) if g.ca2 else 0,
                        'assignment': float(g.assignment) if g.assignment else 0,
                        'exam': float(g.exam) if g.exam else 0,
                    },
                    'total': float(g.total) if g.total else None,
                    'grade': g.grade,
                }
                for g in grades
            ]

            totals = [g.total for g in grades if g.total is not None]
            average = round(sum(totals) / len(totals), 2) if totals else None

            ReportCard.objects.update_or_create(
                student=student,
                term=term,
                academic_year=academic_year,
                defaults={
                    'school': school,
                    'grades': grade_snapshot,
                    'average': average,
                    'is_released': False,
                },
            )
            generated += 1

        ReportCardService._compute_ranks(school, class_id, term, academic_year)
        return generated

    @staticmethod
    def _compute_ranks(school, class_id, term, academic_year):
        cards = ReportCard.objects.filter(
            school=school,
            student__student_profile__class_group_id=class_id,
            term=term,
            academic_year=academic_year,
        ).order_by('-average')
        for rank, card in enumerate(cards, start=1):
            card.class_rank = rank
            card.save(update_fields=['class_rank'])

    @staticmethod
    def release(user, term, academic_year, class_id=None):
        if user.role not in RELEASE_ROLES:
            raise PermissionDenied('Only principals or admins can release report cards.')
        qs = ReportCard.objects.filter(
            school=user.school,
            term=term,
            academic_year=academic_year,
            is_released=False,
        )
        if class_id:
            qs = qs.filter(student__student_profile__class_group_id=class_id)
        updated = qs.update(
            is_released=True,
            released_by=user,
            released_at=timezone.now(),
        )
        return {'released': updated}
