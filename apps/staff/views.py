import uuid
import secrets
import string
from datetime import datetime

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User
from .models import TeacherProfile, StaffProfile
from .serializers import StaffSerializer
from .permissions import IsSchoolAdminRole


def _platform_domain():
    from django.conf import settings
    return (getattr(settings, 'PLATFORM_DOMAIN', '') or 'clarriva.com').strip()


def _as_date(value):
    """A date from a CSV cell, or None. A bad cell never fails the whole import."""
    if not value:
        return None
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


class StaffViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = User.objects.filter(
        role__in=('principal', 'teacher', 'bursary', 'school_admin', 'admin_officer')
    ).select_related('teacher_profile', 'staff_profile').all()
    serializer_class = StaffSerializer

    def get_permissions(self):
        admin_only = {'create_account', 'import_csv'}
        if self.action in admin_only:
            return [IsSchoolAdminRole()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset().filter(
            role__in=('principal', 'teacher', 'bursary', 'school_admin', 'admin_officer')
        )
        role = self.request.query_params.get('role')
        search = self.request.query_params.get('search')
        if role:
            qs = qs.filter(role=role)
        if search:
            qs = qs.filter(first_name__icontains=search) | qs.filter(
                last_name__icontains=search)
        return qs

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        import csv, io
        csv_data = request.data.get('csv', '')
        reader = csv.DictReader(io.StringIO(csv_data))
        created, errors, credentials = 0, [], []
        school = getattr(request.user, 'school', None)
        for i, row in enumerate(reader, start=2):
            first_name = row.get('first_name', '').strip()
            last_name = row.get('last_name', '').strip()
            if not first_name or not last_name:
                errors.append(f'Row {i}: missing first_name or last_name')
                continue
            email = row.get('email', '').strip().lower()
            if not email:
                errors.append(f'Row {i}: email is required')
                continue
            if User.objects.filter(email__iexact=email).exists():
                errors.append(f'Row {i}: {email} already has an account')
                continue
            try:
                username = f'staff_{uuid.uuid4().hex[:12]}'
                raw_role = row.get('role', 'Teacher').strip()
                profile_role = StaffSerializer._map_role(raw_role)
                # Every imported teacher leaves with a working login.
                password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
                joined = _as_date(row.get('date_joined', '').strip())
                user = User.objects.create_user(
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    phone=row.get('phone', '').strip() or '',
                    role=profile_role,
                    school=school,
                    password=password,
                )
                user.must_change_password = True
                user.save(update_fields=['must_change_password'])
                if profile_role == 'teacher':
                    TeacherProfile.objects.create(
                        user=user,
                        school=school,
                        qualification=row.get('qualification', '').strip() or None,
                        subjects=row.get('subjects', '').strip(),
                        date_joined=joined,
                        status='active',
                    )
                else:
                    StaffProfile.objects.create(
                        user=user,
                        school=school,
                        designation=row.get('designation', raw_role),
                        qualification=row.get('qualification', '').strip() or None,
                        subjects=row.get('subjects', '').strip(),
                        date_joined=joined,
                        status='active',
                    )
                created += 1
                credentials.append({
                    'name': f'{first_name} {last_name}'.strip(),
                    'email': email,
                    'password': password,
                    'role': user.get_role_display(),
                })
            except Exception as e:
                errors.append(f'Row {i}: {str(e)}')
        return Response({'created': created, 'errors': errors, 'credentials': credentials})

    @action(detail=True, methods=['post'])
    def create_account(self, request, pk=None):
        user = self.get_object()
        if not user.email:
            name_part = user.username or f'staff{user.id}'
            user.email = f'{name_part}@{user.school.subdomain}.{_platform_domain()}'
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        user.set_password(password)
        user.save()
        return Response({'email': user.email, 'password': password}, status=status.HTTP_201_CREATED)
