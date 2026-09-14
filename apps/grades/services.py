from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError
from .models import Grade

APPROVAL_ROLES = {'principal', 'school_admin', 'super_admin'}
SUBMISSION_ROLES = {'teacher', 'principal', 'school_admin', 'super_admin'}


class GradeService:

    @staticmethod
    def _base_filter(class_id, subject_id, term, academic_year, school):
        if not all([class_id, subject_id, term, academic_year]):
            raise ValidationError('class_id, subject_id, term, and academic_year are required.')
        return Grade.objects.filter(
            student__student_profile__class_group_id=class_id,
            subject_id=subject_id,
            term=term,
            academic_year=academic_year,
            school=school,
        )

    @staticmethod
    def submit_class(user, class_id, subject_id, term, academic_year):
        if user.role not in SUBMISSION_ROLES:
            raise PermissionDenied('Only teaching staff can submit grades.')
        qs = GradeService._base_filter(class_id, subject_id, term, academic_year, user.school)
        updated = qs.exclude(results_status='approved').update(
            results_status='submitted',
            submitted_by=user,
            submitted_at=timezone.now(),
        )
        return {'submitted': updated}

    @staticmethod
    def approve_class(user, class_id, subject_id, term, academic_year):
        if user.role not in APPROVAL_ROLES:
            raise PermissionDenied('Only principals or admins can approve grades.')
        qs = GradeService._base_filter(class_id, subject_id, term, academic_year, user.school)
        updated = qs.filter(results_status='submitted').update(
            results_status='approved',
            approved_by=user,
            approved_at=timezone.now(),
        )
        return {'approved': updated}

    @staticmethod
    def reject_class(user, class_id, subject_id, term, academic_year, note=''):
        if user.role not in APPROVAL_ROLES:
            raise PermissionDenied('Only principals or admins can reject grades.')
        qs = GradeService._base_filter(class_id, subject_id, term, academic_year, user.school)
        updated = qs.filter(results_status='submitted').update(
            results_status='rejected',
            rejection_note=note,
        )
        return {'rejected': updated}
