from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User
from .models import Student
from .serializers import StudentSerializer
import secrets
import string


class StudentViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Student.objects.select_related('class_group', 'user').all()
    serializer_class = StudentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        # Student self-access
        if user.role == 'student':
            return qs.filter(user=user)

        # Teacher scoping
        if user.role == 'teacher':
            staff = user.staff_set.first()
            if staff:
                teacher_classes = staff.class_set.values_list('id', flat=True)
                qs = qs.filter(class_group_id__in=teacher_classes)

        status = self.request.query_params.get('status')
        class_id = self.request.query_params.get('class_id')
        search = self.request.query_params.get('search')
        if status:
            qs = qs.filter(status=status)
        if class_id:
            qs = qs.filter(class_group_id=class_id)
        if search:
            qs = qs.filter(full_name__icontains=search) | qs.filter(admission_no__icontains=search)
        return qs

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        import csv, io
        csv_data = request.data.get('csv', '')
        class_id = request.data.get('class_id')
        reader = csv.DictReader(io.StringIO(csv_data))
        created, errors = 0, []
        for i, row in enumerate(reader, start=2):
            name = row.get('full_name', '').strip()
            if not name:
                errors.append(f'Row {i}: missing full_name')
                continue
            try:
                seq = Student.objects.filter(school=request.user.school).count() + 1
                Student.objects.create(
                    school=request.user.school,
                    admission_no=row.get('admission_no', '') or f'CLR/{request.user.school_id}/{seq:05d}',
                    full_name=name,
                    gender=row.get('gender', '').strip() or None,
                    class_group_id=class_id or None,
                    guardian_name=row.get('guardian_name', '').strip() or None,
                    guardian_phone=row.get('guardian_phone', '').strip() or None,
                    guardian_email=row.get('guardian_email', '').strip() or None,
                    status='active',
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
        updated = Student.objects.filter(id__in=student_ids, school=request.user.school).update(class_group_id=target_class_id)
        return Response({'promoted': updated})

    def _sanitize_admission(self, admission_no):
        return admission_no.replace('/', '-').replace(' ', '-').replace('.', '-').lower()

    def _generate_student_username(self, student):
        first_name = student.full_name.split()[0].lower()
        suffix = self._sanitize_admission(student.admission_no)
        base = f'{first_name}.{suffix}'
        username = base
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1
        return username

    @action(detail=True, methods=['post'])
    def create_account(self, request, pk=None):
        student = self.get_object()
        if student.user_id:
            return Response({'error': 'Account already exists'}, status=status.HTTP_400_BAD_REQUEST)
        suffix = self._sanitize_admission(student.admission_no)
        email = f'{suffix}@{student.school.subdomain}.clariva.ng'
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        user = User.objects.create_user(
            username=self._generate_student_username(student),
            email=email,
            password=password,
            first_name=student.full_name.split(' ')[0],
            last_name=' '.join(student.full_name.split(' ')[1:]),
            role='student',
            school=student.school,
        )
        student.user = user
        student.save()
        return Response({'email': email, 'password': password}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'])
    def bulk_create_accounts(self, request):
        class_id = request.data.get('class_id')
        if not class_id:
            return Response({'error': 'class_id required'}, status=status.HTTP_400_BAD_REQUEST)
        students = Student.objects.filter(class_group_id=class_id, school=request.user.school, user__isnull=True)
        created = []
        for student in students:
            suffix = self._sanitize_admission(student.admission_no)
            email = f'{suffix}@{student.school.subdomain}.clariva.ng'
            password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
            user = User.objects.create_user(
                username=self._generate_student_username(student),
                email=email,
                password=password,
                first_name=student.full_name.split(' ')[0],
                last_name=' '.join(student.full_name.split(' ')[1:]),
                role='student',
                school=student.school,
            )
            student.user = user
            student.save()
            created.append({'name': student.full_name, 'email': email, 'password': password})
        return Response({'created': created})

    @action(detail=True, methods=['post'])
    def reset_password(self, request, pk=None):
        student = self.get_object()
        if not student.user_id:
            return Response({'error': 'No account exists for this student'}, status=status.HTTP_400_BAD_REQUEST)
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))
        student.user.set_password(password)
        student.user.save()
        return Response({'email': student.user.email, 'password': password})
