from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.mixins import SchoolFilterMixin
from apps.exams.models import TimeTable, TimeSlot
from .serializers import TimeTableSerializer


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
