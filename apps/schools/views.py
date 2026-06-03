import json
from io import StringIO
from django.core import serializers
from django.core.management import call_command
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

        buf = StringIO()
        call_command('dumpdata', '--natural-foreign', '--natural-primary', stdout=buf)
        all_data = json.loads(buf.getvalue())

        school_data = [obj for obj in all_data if obj.get('fields', {}).get('school') == school_id or
                       obj.get('pk') == school_id]
        return Response({'school_id': school_id, 'count': len(school_data), 'data': school_data})

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
