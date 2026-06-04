from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from apps.mixins import SchoolFilterMixin
from apps.accounts.models import User
from .models import Staff
from .serializers import StaffSerializer
import secrets
import string

class StaffViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Staff.objects.all()
    serializer_class = StaffSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        role = self.request.query_params.get('role')
        search = self.request.query_params.get('search')
        if role:
            qs = qs.filter(role=role)
        if search:
            qs = qs.filter(full_name__icontains=search)
        return qs

    @action(detail=True, methods=['post'])
    def create_account(self, request, pk=None):
        staff = self.get_object()
        if staff.user_id:
            return Response({'error': 'Account already exists'}, status=status.HTTP_400_BAD_REQUEST)
        if staff.email:
            email = staff.email
        else:
            name_part = staff.full_name.lower().replace(' ', '.')
            email = f'{name_part}@{staff.school.subdomain}.clariva.ng'
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        name_part = staff.full_name.split()[0].lower()
        base = f'{name_part}{staff.id}'
        username = base
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1
        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=staff.full_name.split(' ')[0],
            last_name=' '.join(staff.full_name.split(' ')[1:]),
            role='teacher',
            school=staff.school,
        )
        staff.user = user
        staff.save()
        return Response({'email': email, 'password': password}, status=status.HTTP_201_CREATED)
