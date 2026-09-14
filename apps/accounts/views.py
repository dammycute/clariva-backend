from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import check_password
from .serializers import AdminCreateUserSerializer, OnboardSerializer, UserSerializer
from .models import User
from apps.base.encryption import hash_value


class IsSuperAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role == 'super_admin'
        )


class IsAdminRole(permissions.BasePermission):
    """Only super_admin and school_admin can create users."""
    def has_permission(self, request, view):
        return (
            request.user
            and request.user.is_authenticated
            and request.user.role in ('super_admin', 'school_admin')
        )


class OnboardView(generics.CreateAPIView):
    """Public endpoint for new school registration. Only creates school_admin accounts."""
    serializer_class = OnboardSerializer
    permission_classes = (permissions.AllowAny,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        refresh = RefreshToken.for_user(user)
        refresh['role'] = user.role
        refresh.access_token['role'] = user.role
        return Response({
            'user': UserSerializer(user).data,
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }, status=201)


class AdminCreateUserView(generics.CreateAPIView):
    """Admin-only endpoint for creating users with role assignment."""
    serializer_class = AdminCreateUserSerializer
    permission_classes = (permissions.IsAuthenticated, IsAdminRole)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserSerializer(user).data, status=201)

class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

class StudentLoginView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        student_id = request.data.get('student_id', '').strip()
        password = request.data.get('password', '')
        school_id = request.data.get('school_id')

        if not student_id:
            return Response({'detail': 'Student ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'detail': 'Password is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not school_id:
            return Response({'detail': 'School ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            admission_hash = hash_value(student_id)
            user = User.objects.get(
                student_profile__admission_no_hash=admission_hash,
                role='student',
                school_id=school_id,
            )
        except User.DoesNotExist:
            return Response({'detail': 'Student ID not found'}, status=status.HTTP_400_BAD_REQUEST)

        if not check_password(password, user.password):
            return Response({'detail': 'Incorrect password'}, status=status.HTTP_400_BAD_REQUEST)

        refresh = RefreshToken.for_user(user)
        refresh['role'] = 'student'
        refresh['school_id'] = str(user.school_id) if user.school_id else None
        refresh.access_token['role'] = 'student'
        refresh.access_token['school_id'] = str(user.school_id) if user.school_id else None
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'role': 'student',
            'student_name': user.get_full_name(),
            'school_id': str(user.school_id) if user.school_id else None,
        })


class UserListView(generics.ListAPIView):
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def get_queryset(self):
        return User.objects.select_related('student_profile', 'student_profile__class_group').all()
