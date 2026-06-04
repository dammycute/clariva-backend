import json
from io import StringIO
from django.core import serializers as dj_serializers
from django.core.management import call_command
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import School, GradingConfig, DEFAULT_GRADE_BOUNDARIES
from .serializers import SchoolSerializer, GradingConfigSerializer


class SchoolViewSet(viewsets.ModelViewSet):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    permission_classes = (permissions.IsAuthenticated,)

    @action(detail=True, methods=['get', 'put', 'patch'])
    def grading(self, request, pk=None):
        school = self.get_object()
        config, _ = GradingConfig.objects.get_or_create(school=school, defaults={'grade_boundaries': DEFAULT_GRADE_BOUNDARIES})

        if request.method == 'GET':
            return Response(GradingConfigSerializer(config).data)

        serializer = GradingConfigSerializer(config, data=request.data, partial=request.method == 'PATCH')
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def backup(self, request):
        school_id = request.user.school_id
        if not school_id:
            return Response({'error': 'No school assigned'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.students.models import Student
        from apps.classes.models import Class
        from apps.staff.models import Staff
        from apps.fees.models import FeeItem, FeeInvoice, FeeInvoiceItem
        from apps.attendance.models import Attendance
        from apps.grades.models import Grade
        from apps.exams.models import Subject, TimeTable, ReportCard
        from apps.comms.models import Announcement

        models_to_backup = {
            'students': (Student,),
            'classes': (Class,),
            'staff': (Staff,),
            'fee_items': (FeeItem,),
            'fee_invoices': (FeeInvoice,),
            'fee_invoice_items': (FeeInvoiceItem,),
            'attendance': (Attendance,),
            'grades': (Grade,),
            'subjects': (Subject,),
            'timetables': (TimeTable,),
            'report_cards': (ReportCard,),
            'announcements': (Announcement,),
        }

        backup_data = {}
        counts = {}
        for name, (model,) in models_to_backup.items():
            qs = model.objects.filter(school_id=school_id)
            counts[name] = qs.count()
            backup_data[name] = dj_serializers.serialize('json', qs)

        return Response({
            'school_id': school_id,
            'version': '1.0',
            'exported_at': timezone.now().isoformat(),
            'data': backup_data,
            'counts': counts,
        })

    @action(detail=False, methods=['post'])
    def restore(self, request):
        school_id = request.user.school_id
        if not school_id:
            return Response({'error': 'No school assigned'}, status=status.HTTP_400_BAD_REQUEST)

        data = request.data
        if isinstance(data, str):
            data = json.loads(data)

        buf = StringIO(json.dumps(data.get('data', data)))
        try:
            call_command('loaddata', stdin=buf, verbosity=0)
            return Response({'restored': True})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
