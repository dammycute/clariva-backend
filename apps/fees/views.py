from rest_framework import viewsets
from rest_framework.response import Response
from django.db import transaction
from apps.mixins import SchoolFilterMixin
from .models import FeeItem, FeeInvoice
from .serializers import FeeItemSerializer, FeeInvoiceSerializer


class FeeItemViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = FeeItem.objects.all()
    serializer_class = FeeItemSerializer


class FeeInvoiceViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = FeeInvoice.objects.select_related('student', 'fee_item').prefetch_related('items__fee_item').all()
    serializer_class = FeeInvoiceSerializer

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
