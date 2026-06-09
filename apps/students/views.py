from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User, StudentAccessCode
from .serializers import StudentSerializer
import secrets
import string


class StudentViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = User.objects.filter(role='student').select_related('class_group').all()
    serializer_class = StudentSerializer

    def get_queryset(self):
        qs = super().get_queryset().filter(role='student')
        user = self.request.user

        # Student self-access
        if user.role == 'student':
            return qs.filter(id=user.id)

        # Teacher scoping
        if user.role == 'teacher':
            staff = user.staff_profile
            if staff:
                teacher_classes = staff.class_set.values_list('id', flat=True)
                qs = qs.filter(class_group_id__in=teacher_classes)

        student_status = self.request.query_params.get('status')
        class_id = self.request.query_params.get('class_id')
        search = self.request.query_params.get('search')
        if student_status:
            qs = qs.filter(student_status=student_status)
        if class_id:
            qs = qs.filter(class_group_id=class_id)
        if search:
            qs = qs.filter(first_name__icontains=search) | qs.filter(
                last_name__icontains=search) | qs.filter(admission_no__icontains=search)
        return qs

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        import csv, io
        csv_data = request.data.get('csv', '')
        class_id = request.data.get('class_id')
        reader = csv.DictReader(io.StringIO(csv_data))
        created, errors = 0, []
        school = getattr(request.user, 'school', None)
        for i, row in enumerate(reader, start=2):
            name = row.get('full_name', '').strip()
            if not name:
                errors.append(f'Row {i}: missing full_name')
                continue
            name_parts = name.split(' ', 1)
            first_name = name_parts[0]
            last_name = name_parts[1] if len(name_parts) > 1 else ''
            try:
                seq = User.objects.filter(school=school, role='student').count() + 1
                admission_no = row.get('admission_no', '') or f'CLR/{request.user.school_id}/{seq:05d}'
                username = f'student.{seq}'
                User.objects.create(
                    school=school,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    admission_no=admission_no,
                    gender=row.get('gender', '').strip() or None,
                    class_group_id=class_id or None,
                    guardian_name=row.get('guardian_name', '').strip() or None,
                    guardian_phone=row.get('guardian_phone', '').strip() or None,
                    guardian_email=row.get('guardian_email', '').strip() or None,
                    student_status='active',
                    role='student',
                )
                created += 1
            except Exception as e:
                errors.append(f'Row {i}: {str(e)}')
        return Response({'created': created, 'errors': errors})

    @action(detail=False, methods=['post'])
    def promote(self, request):
        student_ids = request.data.get('student_ids', [])
        target_class_id = request.data.get('target_class_id')
        if not student_ids or not target_class_id:
            return Response({'error': 'student_ids and target_class_id are required'}, status=status.HTTP_400_BAD_REQUEST)
        updated = User.objects.filter(
            id__in=student_ids, school=request.user.school, role='student'
        ).update(class_group_id=target_class_id)
        return Response({'promoted': updated})

    def _sanitize_admission(self, admission_no):
        return admission_no.replace('/', '-').replace(' ', '-').replace('.', '-').lower()

    def _generate_student_username(self, admission_no, school):
        base = f'student.{self._sanitize_admission(admission_no)}'
        username = base
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1
        return username

    @action(detail=True, methods=['post'])
    def create_account(self, request, pk=None):
        student = self.get_object()
        if student.has_usable_password():
            return Response({'error': 'Account already exists'}, status=status.HTTP_400_BAD_REQUEST)
        suffix = self._sanitize_admission(student.admission_no or student.id)
        email = f'{suffix}@{student.school.subdomain}.clariva.ng'
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        student.username = self._generate_student_username(student.admission_no or student.id, student.school)
        student.email = email
        student.set_password(password)
        student.save()
        return Response({'email': email, 'password': password}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def bulk_create_accounts(self, request):
        class_id = request.data.get('class_id')
        if not class_id:
            return Response({'error': 'class_id required'}, status=status.HTTP_400_BAD_REQUEST)
        students = User.objects.filter(
            class_group_id=class_id, school=request.user.school, role='student',
            password='',
        )
        created = []
        for student in students:
            suffix = self._sanitize_admission(student.admission_no or student.id)
            email = f'{suffix}@{student.school.subdomain}.clariva.ng'
            password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
            student.username = self._generate_student_username(student.admission_no or student.id, student.school)
            student.email = email
            student.set_password(password)
            student.save()
            created.append({'name': student.get_full_name(), 'email': email, 'password': password})
        return Response({'created': created})

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        student = self.get_object()
        if not student.has_usable_password():
            return Response({'error': 'No account exists for this student'}, status=status.HTTP_400_BAD_REQUEST)
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        student.set_password(password)
        student.save()
        return Response({'email': student.email, 'password': password})

    @action(detail=True, methods=['get'])
    def timeline(self, request, pk=None):
        student = self.get_object()
        from apps.attendance.models import Attendance
        from apps.exams.models import ExamSession
        from apps.fees.models import FeeInvoice
        from apps.grades.models import Grade

        events = []

        for att in Attendance.objects.filter(student=student).order_by('-date')[:20]:
            events.append({
                'type': 'attendance',
                'date': att.date.isoformat() if att.date else None,
                'title': f'Attendance: {att.status}',
                'description': f'Marked as {att.status} on {att.date}',
            })

        for ses in ExamSession.objects.filter(student=student).select_related('exam').order_by('-submitted_at')[:20]:
            if ses.submitted_at:
                events.append({
                    'type': 'exam',
                    'date': ses.submitted_at.isoformat(),
                    'title': f'Exam: {ses.exam.title}',
                    'description': f'Score: {ses.score}/{ses.total_marks}',
                })

        for inv in FeeInvoice.objects.filter(student=student).order_by('-created_at')[:20]:
            events.append({
                'type': 'fee',
                'date': inv.created_at.isoformat(),
                'title': f'Fee: {inv.fee_item.name if inv.fee_item else "Invoice"}',
                'description': f'₦{inv.amount_paid:,.2f} paid of ₦{inv.amount_due:,.2f}',
            })

        for g in Grade.objects.filter(student=student).select_related('subject').order_by('-created_at')[:20]:
            events.append({
                'type': 'grade',
                'date': g.created_at.isoformat() if g.created_at else None,
                'title': f'Grade: {g.subject.name if g.subject else "Subject"}',
                'description': f'Total: {g.total} ({g.grade})',
            })

        events.sort(key=lambda e: e['date'] or '', reverse=True)
        return Response(events[:50])

    def perform_create(self, serializer):
        serializer.save(role='student')
