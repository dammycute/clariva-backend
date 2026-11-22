from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q
from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User, StudentAccessCode
from apps.staff.permissions import IsSchoolAdminRole
from apps.permissions import IsStaffRole
from apps.accounts.sessions import end_session
from apps.fees.services import FeeService
from .serializers import StudentSerializer, has_login
import secrets
import string


class StudentViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = User.objects.filter(role='student').select_related('student_profile__class_group').all()
    serializer_class = StudentSerializer

    def get_permissions(self):
        admin_only = {'promote', 'bulk_create_accounts', 'import_csv', 'reset_password'}
        if self.action in admin_only:
            return [IsSchoolAdminRole()]
        if self.action == 'sign_out_everywhere':
            return [IsStaffRole()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset().filter(role='student')
        user = self.request.user

        # Student self-access
        if user.role == 'student':
            return qs.filter(id=user.id)
        if user.role == 'parent':
            return qs.none()

        # Teacher scoping
        if user.role == 'teacher':
            teacher_classes = user.class_set.values_list('id', flat=True)
            if teacher_classes:
                qs = qs.filter(student_profile__class_group_id__in=teacher_classes)

        student_status = self.request.query_params.get('status')
        class_id = self.request.query_params.get('class_id')
        search = self.request.query_params.get('search')
        if student_status:
            qs = qs.filter(student_profile__student_status=student_status)
        if class_id:
            qs = qs.filter(student_profile__class_group_id=class_id)
        if search:
            qs = qs.filter(first_name__icontains=search) | qs.filter(
                last_name__icontains=search)
        return qs

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        """Create students from CSV text. Admission numbers and usernames are always generated.

        Columns: full_name (or first_name + last_name), gender, guardian_name, guardian_phone,
        guardian_email, and optionally class (a class name from this school). An admission_no
        column, if present, is ignored.
        """
        import csv, io
        from apps.classes.models import Class
        from apps.base.encryption import hash_value
        from apps.students.models import StudentProfile
        from .serializers import next_admission_no, unique_username

        csv_data = (request.data.get('csv', '') or '').lstrip('﻿')
        default_class_id = request.data.get('class_id') or None
        school = request.user.school
        classes = {c.name.strip().lower(): c for c in Class.objects.filter(school=school)}
        if default_class_id and not Class.objects.filter(pk=default_class_id, school=school).exists():
            return Response({'error': 'Choose a class from your school.'}, status=status.HTTP_400_BAD_REQUEST)

        reader = csv.DictReader(io.StringIO(csv_data))
        reader.fieldnames = [(f or '').strip().lower() for f in (reader.fieldnames or [])]
        created, errors, students = 0, [], []
        for i, raw in enumerate(reader, start=2):
            row = {k: (v or '').strip() for k, v in raw.items() if k}
            name = row.get('full_name') or f"{row.get('first_name', '')} {row.get('last_name', '')}".strip()
            if not name:
                errors.append(f'Row {i}: missing name (use full_name, or first_name and last_name)')
                continue
            first, _, last = name.partition(' ')
            class_name = row.get('class', '')
            cls = classes.get(class_name.lower()) if class_name else None
            if class_name and not cls:
                errors.append(f'Row {i}: class "{class_name}" was not found')
                continue
            try:
                with transaction.atomic():
                    adm = next_admission_no(school)
                    user = User(school=school, username=unique_username(adm), first_name=first,
                                last_name=last.strip(), gender=row.get('gender') or None, role='student')
                    user.set_unusable_password()
                    user.save()
                    StudentProfile.objects.create(
                        user=user, school=school, admission_no=adm, admission_no_hash=hash_value(adm),
                        class_group_id=cls.id if cls else default_class_id,
                        guardian_name=row.get('guardian_name') or None,
                        guardian_phone=row.get('guardian_phone') or None,
                        guardian_email=row.get('guardian_email') or None,
                        student_status='active',
                    )
                FeeService.invoice_student(user)
                created += 1
                students.append({'name': name, 'admission_no': adm})
            except Exception as e:
                errors.append(f'Row {i}: {e}')
        return Response({'created': created, 'errors': errors, 'students': students})

    @action(detail=False, methods=['post'])
    def promote(self, request):
        student_ids = request.data.get('student_ids', [])
        target_class_id = request.data.get('target_class_id')
        if not student_ids or not target_class_id:
            return Response({'error': 'student_ids and target_class_id are required'}, status=status.HTTP_400_BAD_REQUEST)
        from apps.students.models import StudentProfile
        updated = StudentProfile.objects.filter(
            user_id__in=student_ids, user__school=request.user.school
        ).update(class_group_id=target_class_id)
        for student in User.objects.filter(id__in=student_ids, school=request.user.school, role='student'):
            FeeService.invoice_student(student)
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
        if has_login(student):
            return Response({'error': 'Account already exists'}, status=status.HTTP_400_BAD_REQUEST)
        sp = getattr(student, 'student_profile', None)
        identifier = sp.admission_no if sp and sp.admission_no else str(student.id)
        suffix = self._sanitize_admission(identifier)
        email = f'{suffix}@{student.school.subdomain}.clariva.ng'
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        student.username = self._generate_student_username(identifier, student.school)
        student.email = email
        student.set_password(password)
        student.save()
        return Response({'admission_no': identifier, 'email': email, 'password': password},
                        status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def bulk_create_accounts(self, request):
        class_id = request.data.get('class_id')
        if not class_id:
            return Response({'error': 'class_id required'}, status=status.HTTP_400_BAD_REQUEST)
        students = User.objects.filter(
            student_profile__class_group_id=class_id, school=request.user.school, role='student',
        ).filter(Q(password='') | Q(password__startswith='!'))
        created = []
        for student in students:
            sp = getattr(student, 'student_profile', None)
            identifier = sp.admission_no if sp and sp.admission_no else str(student.id)
            suffix = self._sanitize_admission(identifier)
            email = f'{suffix}@{student.school.subdomain}.clariva.ng'
            password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
            student.username = self._generate_student_username(identifier, student.school)
            student.email = email
            student.set_password(password)
            student.save()
            created.append({'name': student.get_full_name(), 'admission_no': identifier,
                            'email': email, 'password': password})
        return Response({'created': created})

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        student = self.get_object()
        if not has_login(student):
            return Response({'error': 'No account exists for this student'}, status=status.HTTP_400_BAD_REQUEST)
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        student.set_password(password)
        student.save()
        sp = getattr(student, 'student_profile', None)
        return Response({'admission_no': sp.admission_no if sp else None, 'email': student.email,
                         'password': password})

    @action(detail=True, methods=['post'])
    def sign_out_everywhere(self, request, pk=None):
        """Sign the student out of every device. Use it when a device is lost or dead during an
        exam, or when someone else may be using the account. The student can sign in again at once."""
        student = self.get_object()
        end_session(student)
        return Response({'signed_out': True})

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
        user = serializer.save(role='student', school=self.request.user.school)
        self._log_activity(user, 'created')
        return user
