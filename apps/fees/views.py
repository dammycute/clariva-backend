from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
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
    queryset = FeeItem.objects.order_by('name', 'id')
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

    @action(detail=True, methods=['get'])
    def delete_impact(self, request, pk=None):
        """How many invoices bill this fee, and how many of them have payments."""
        return Response(FeeService.delete_impact(self.get_object()))

    def destroy(self, request, *args, **kwargs):
        """Delete a fee. If students were billed for it, say what to do with their invoices:
        ?with_invoices=true deletes the unpaid invoices too; ?keep_invoices=true leaves them.
        Invoices with a payment are never deleted."""
        item = self.get_object()
        impact = FeeService.delete_impact(item)
        with_invoices = request.query_params.get('with_invoices') == 'true'
        keep_invoices = request.query_params.get('keep_invoices') == 'true'
        if impact['invoices'] and not (with_invoices or keep_invoices):
            return Response(
                {'error': f"{impact['invoices']} invoice(s) were made from this fee. "
                          'Choose whether to delete them too or keep them.', **impact},
                status=status.HTTP_409_CONFLICT)
        if impact['invoices'] and with_invoices:
            try:
                FeeService.remove_invoices_for_item(item)
            except ValueError as e:
                return Response({'error': str(e), **impact}, status=status.HTTP_409_CONFLICT)
        self.perform_destroy(item)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FeeInvoiceViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = FeeInvoice.objects.select_related(
        'student', 'fee_item', 'student__student_profile__class_group',
    ).prefetch_related('items__fee_item').order_by('-created_at', 'id')   # fixed order, so pages never overlap
    serializer_class = FeeInvoiceSerializer
    permission_classes = (FeeRolePermission,)

    def get_queryset(self):
        qs = super().get_queryset()
        student_id = self.request.query_params.get('student_id')
        status = self.request.query_params.get('status')
        class_group = self.request.query_params.get('class_group')
        if class_group:
            qs = qs.filter(student__student_profile__class_group_id=class_group)
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
