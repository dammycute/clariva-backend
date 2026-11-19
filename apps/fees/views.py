from rest_framework import viewsets, permissions
from rest_framework.response import Response
from django.db import transaction
from apps.mixins import SchoolFilterMixin
from .models import FeeItem, FeeInvoice
from .serializers import FeeItemSerializer, FeeInvoiceSerializer
from .services import FeeService


FINANCE_ROLES = {'school_admin', 'admin_officer', 'bursary', 'super_admin'}


class FeeRolePermission(permissions.IsAuthenticated):
    """Allow read to all authenticated; write restricted to finance roles."""
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return getattr(request.user, 'role', None) in FINANCE_ROLES


class FeeItemViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = FeeItem.objects.all()
    serializer_class = FeeItemSerializer
    permission_classes = (FeeRolePermission,)

    # Saving a fee bills the students it applies to. Students who already have it are skipped,
    # so saving again is safe and also catches anyone added since.
    def perform_create(self, serializer):
        item = super().perform_create(serializer)
        FeeService.invoice_students_for_item(item)
        return item

    def perform_update(self, serializer):
        item = super().perform_update(serializer)
        FeeService.invoice_students_for_item(item)
        return item


class FeeInvoiceViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = FeeInvoice.objects.select_related('student', 'fee_item').prefetch_related('items__fee_item').all()
    serializer_class = FeeInvoiceSerializer
    permission_classes = (FeeRolePermission,)

    def get_queryset(self):
        qs = super().get_queryset()
        student_id = self.request.query_params.get('student_id')
        status = self.request.query_params.get('status')
        if student_id:
            qs = qs.filter(student_id=student_id)
        if status:
            qs = qs.filter(status=status)
        return qs

    def partial_update(self, request, *args, **kwargs):
        with transaction.atomic():
            instance = self.get_object()
            locked = FeeInvoice.objects.select_for_update().get(pk=instance.pk)
            serializer = self.get_serializer(locked, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            self.perform_update(serializer)
            return Response(serializer.data)
