from django.db import models
from rest_framework.exceptions import PermissionDenied
from rest_framework.pagination import PageNumberPagination
from apps.audit.models import ActivityLog
from apps.schools.models import School


class CustomPagination(PageNumberPagination):
    page_size_query_param = 'page_size'
    max_page_size = 10000


class SchoolFilterMixin:
    """Auto-filter queryset by request.user.school and set school on create."""

    def get_queryset(self):
        user = self.request.user
        if not user.school_id:
            if user.is_superuser or user.role == 'super_admin':
                return self.queryset.all()
            raise PermissionDenied(
                'No school is assigned to your account. Contact your administrator.'
            )
        if not user.is_superuser and user.role != 'super_admin':
            school = School.objects.get(pk=user.school_id)
            if school.status == 'suspended':
                raise PermissionDenied('This school account has been suspended.')
        return self.queryset.filter(school=user.school)

    def perform_create(self, serializer):
        instance = serializer.save(school=self.request.user.school)
        self._log_activity(instance, 'created')
        return instance

    def perform_update(self, serializer):
        instance = serializer.save()
        self._log_activity(instance, 'updated')
        return instance

    def perform_destroy(self, instance):
        self._log_activity(instance, 'deleted')
        return super().perform_destroy(instance)

    def _log_activity(self, instance, action):
        if not self.request.user or not self.request.user.is_authenticated:
            return
        ActivityLog.objects.create(
            school=getattr(self.request.user, 'school', None),
            user=self.request.user,
            action=action,
            model_name=type(instance).__name__,
            object_id=str(instance.pk),
            object_repr=str(instance)[:255],
            ip_address=self.request.META.get('REMOTE_ADDR', '')[:45],
        )
