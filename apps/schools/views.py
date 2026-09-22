import json
from io import StringIO
from django.core import serializers as dj_serializers
from django.core.management import call_command
from django.utils import timezone
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from apps.audit.models import ActivityLog
from apps.staff.permissions import IsSchoolAdminRole
from .models import School, GradingConfig, DEFAULT_GRADE_BOUNDARIES, DEFAULT_COMPONENTS
from .serializers import SchoolSerializer, GradingConfigSerializer
from .analytics import get_summary


class IsSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'super_admin'
        )


class SchoolViewSet(viewsets.ModelViewSet):
    queryset = School.objects.all()
    serializer_class = SchoolSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        user = self.request.user
        if not user.school_id:
            if user.is_superuser or user.role == 'super_admin':
                return School.objects.all()
            raise PermissionDenied(
                'No school is assigned to your account. Contact your administrator.'
            )
        if not user.is_superuser and user.role != 'super_admin':
            school = School.objects.get(pk=user.school_id)
            if school.status == 'suspended':
                raise PermissionDenied('This school account has been suspended.')
        return School.objects.filter(pk=user.school_id)

    def get_permissions(self):
        if self.action in ('update', 'partial_update', 'destroy', 'create'):
            return [permissions.IsAuthenticated(), IsSuperAdmin()]
        if self.action == 'backup':
            return [permissions.IsAuthenticated(), IsSchoolAdminRole()]
        if self.action == 'grading' and self.request.method in ('PUT', 'PATCH'):
            return [permissions.IsAuthenticated(), IsSchoolAdminRole()]
        return [permissions.IsAuthenticated()]

    @action(detail=True, methods=['get'])
    def analytics(self, request, pk=None):
        school = self.get_object()
        data = get_summary(school.id)
        data['school_name'] = school.name
        data['current_term'] = school.current_term
        data['current_academic_year'] = school.current_academic_year
        return Response(data)

    @action(detail=True, methods=['get', 'put', 'patch'])
    def grading(self, request, pk=None):
        school = self.get_object()
        config, _ = GradingConfig.objects.get_or_create(
            school=school,
            defaults={'grade_boundaries': DEFAULT_GRADE_BOUNDARIES, 'components': DEFAULT_COMPONENTS},
        )

        if request.method == 'GET':
            return Response(GradingConfigSerializer(config).data)

        serializer = GradingConfigSerializer(config, data=request.data, partial=request.method == 'PATCH')
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)

    @action(detail=False, methods=['get'])
    def backup(self, request):
        if request.user.role == 'super_admin' and not request.user.school_id:
            school_id = request.query_params.get('school_id')
            if not school_id:
                return Response(
                    {'error': 'school_id query parameter is required'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not School.objects.filter(pk=school_id).exists():
                return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            school_id = request.user.school_id
            if not school_id:
                return Response({'error': 'No school assigned'}, status=status.HTTP_400_BAD_REQUEST)

        from apps.accounts.models import User
        from apps.classes.models import Class
        from apps.staff.models import TeacherProfile, StaffProfile
        from apps.fees.models import FeeItem, FeeInvoice, FeeInvoiceItem
        from apps.attendance.models import Attendance
        from apps.grades.models import Grade
        from apps.exams.models import Subject, TimeTable, ReportCard
        from apps.comms.models import Announcement

        models_to_backup = {
            'students': (User,),
            'classes': (Class,),
            'teachers': (TeacherProfile,),
            'staff': (StaffProfile,),
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

        ActivityLog.objects.create(
            school_id=school_id,
            user=request.user,
            action='exported',
            model_name='School',
            object_id=str(school_id),
            object_repr=f'Backup export of school {school_id}',
            ip_address=request.META.get('REMOTE_ADDR', '')[:45],
        )

        return Response({
            'school_id': school_id,
            'version': '1.0',
            'exported_at': timezone.now().isoformat(),
            'data': backup_data,
            'counts': counts,
        })

    @action(detail=False, methods=['post'])
    def restore(self, request):
        if request.user.role not in ('super_admin', 'school_admin'):
            return Response(
                {'error': 'Only super admins and school admins can restore data'},
                status=status.HTTP_403_FORBIDDEN,
            )

        if request.user.role == 'super_admin':
            payload_school = (
                request.data.get('school_id') if isinstance(request.data, dict) else None
            )
            school_id = payload_school or request.user.school_id
        else:
            school_id = request.user.school_id

        if not school_id:
            return Response(
                {'error': 'No school assigned. Include school_id in the backup payload.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        confirm = request.data.get('confirm', False)
        if not confirm:
            return Response(
                {'error': 'Pass confirm=true to proceed with restore. This will overwrite existing data.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data
        if isinstance(data, str):
            data = json.loads(data)

        raw_data = data.get('data', data)
        if isinstance(raw_data, str):
            raw_data = json.loads(raw_data)

        ALLOWED_MODELS = {
            'accounts.User', 'classes.Class', 'staff.TeacherProfile',
            'staff.StaffProfile', 'fees.FeeItem', 'fees.FeeInvoice',
            'fees.FeeInvoiceItem', 'attendance.Attendance', 'grades.Grade',
            'exams.Subject', 'exams.TimeTable', 'exams.ReportCard',
            'comms.Announcement',
        }

        if isinstance(raw_data, dict):
            items = raw_data.values()
        elif isinstance(raw_data, list):
            items = raw_data
        else:
            return Response({'error': 'Invalid data format'}, status=status.HTTP_400_BAD_REQUEST)

        for item in items:
            if not isinstance(item, dict) or 'model' not in item:
                return Response(
                    {'error': 'Invalid serialization format — expected Django serialized objects'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if item['model'] not in ALLOWED_MODELS:
                return Response(
                    {'error': f'Model "{item["model"]}" is not allowed for restore'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            fields = item.get('fields', {})
            if 'is_superuser' in fields and fields['is_superuser']:
                return Response(
                    {'error': 'Cannot restore superuser accounts'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            item_school = fields.get('school') or fields.get('school_id')
            if item_school and str(item_school) != str(school_id):
                return Response(
                    {'error': f'Data belongs to school {item_school}, not your school {school_id}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        buf = StringIO(json.dumps(raw_data))
        try:
            call_command('loaddata', stdin=buf, verbosity=0)
            return Response({'restored': True, 'items_processed': len(raw_data)})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated, IsSuperAdmin])
def system_stats(request):
    from apps.accounts.models import User
    from apps.students.models import StudentProfile
    from apps.staff.models import TeacherProfile, StaffProfile
    from apps.classes.models import Class
    from apps.fees.models import FeeInvoice
    from apps.exams.models import Subject
    from apps.attendance.models import Attendance
    from django.db.models import Sum, Count, Q

    schools = School.objects.all()
    total_schools = schools.count()
    active_schools = schools.filter(status='active').count()
    suspended_schools = schools.filter(status='suspended').count()

    total_students = StudentProfile.objects.count()
    active_students = StudentProfile.objects.filter(student_status='active').count()

    total_staff = TeacherProfile.objects.count() + StaffProfile.objects.count()
    total_classes = Class.objects.count()
    total_subjects = Subject.objects.count()

    fee_agg = FeeInvoice.objects.aggregate(
        total_due=Sum('amount_due'),
        total_paid=Sum('amount_paid'),
    )
    total_due = float(fee_agg['total_due'] or 0)
    total_paid = float(fee_agg['total_paid'] or 0)

    total_attendance = Attendance.objects.count()
    present_count = Attendance.objects.filter(status='present').count()

    recent_schools = list(schools.order_by('-created_at').values(
        'id', 'name', 'subdomain', 'status', 'plan', 'current_academic_year', 'created_at'
    )[:10])
    for s in recent_schools:
        s['id'] = str(s['id'])
        s['created_at'] = s['created_at'].isoformat() if s['created_at'] else None
        s['student_count'] = StudentProfile.objects.filter(school_id=s['id']).count()

    return Response({
        'total_schools': total_schools,
        'active_schools': active_schools,
        'suspended_schools': suspended_schools,
        'total_students': total_students,
        'active_students': active_students,
        'total_staff': total_staff,
        'total_classes': total_classes,
        'total_subjects': total_subjects,
        'fees': {
            'total_due': total_due,
            'total_paid': total_paid,
            'outstanding': total_due - total_paid,
        },
        'attendance': {
            'total': total_attendance,
            'present': present_count,
            'rate': round(present_count / total_attendance * 100, 1) if total_attendance > 0 else 0,
        },
        'recent_schools': recent_schools,
    })
