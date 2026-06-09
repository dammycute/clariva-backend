import uuid
import secrets
import string

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User
from .models import Staff
from .serializers import StaffSerializer


class StaffViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Staff.objects.select_related('user').all()
    serializer_class = StaffSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        role = self.request.query_params.get('role')
        search = self.request.query_params.get('search')
        if role:
            qs = qs.filter(role=role)
        if search:
            qs = qs.filter(user__first_name__icontains=search) | qs.filter(
                user__last_name__icontains=search)
        return qs

    def perform_create(self, serializer):
        serializer.save(school=self.request.user.school)

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        import csv, io
        csv_data = request.data.get('csv', '')
        reader = csv.DictReader(io.StringIO(csv_data))
        created, errors = 0, []
        school = getattr(request.user, 'school', None)
        for i, row in enumerate(reader, start=2):
            first_name = row.get('first_name', '').strip()
            last_name = row.get('last_name', '').strip()
            if not first_name or not last_name:
                errors.append(f'Row {i}: missing first_name or last_name')
                continue
            email = row.get('email', '').strip()
            if not email:
                errors.append(f'Row {i}: email is required')
                continue
            try:
                username = f'staff_{uuid.uuid4().hex[:12]}'
                user = User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=row.get('phone', '').strip() or '',
                    role=StaffSerializer._map_role(row.get('role', 'Teacher').strip()),
                    school=school,
                )
                subjects = row.get('subjects', '').strip()
                Staff.objects.create(
                    user=user,
                    school=school,
                    role=row.get('role', 'Teacher').strip(),
                    qualification=row.get('qualification', '').strip() or None,
                    subjects=[s.strip() for s in subjects.split(';') if s.strip()] if subjects else None,
                    date_joined=row.get('date_joined', '').strip() or None,
                    status='active',
                )
                created += 1
            except Exception as e:
                errors.append(f'Row {i}: {str(e)}')
        return Response({'created': created, 'errors': errors})

    @action(detail=True, methods=['post'])
    def create_account(self, request, pk=None):
        staff = self.get_object()
        if not staff.user.email:
            name_part = staff.user.username or f'staff{staff.id}'
            staff.user.email = f'{name_part}@{staff.school.subdomain}.clariva.ng'
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        staff.user.set_password(password)
        staff.user.save()
        return Response({'email': staff.user.email, 'password': password}, status=status.HTTP_201_CREATED)
