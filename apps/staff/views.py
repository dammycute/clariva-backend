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
        email = staff.email or f'staff{staff.id}@school.local'
        password = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(10))
        user = User.objects.create_user(
            username=email.split('@')[0],
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
