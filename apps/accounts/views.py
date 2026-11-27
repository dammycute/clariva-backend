import logging
import secrets
import string

from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from django.conf import settings
from django.contrib.auth.hashers import check_password
from .serializers import (
    AdminCreateUserSerializer, ChangePasswordSerializer, GenerateAdminLoginSerializer,
    OnboardSerializer, SelfUpdateSerializer, UserSerializer,
)
from .models import User
from .sessions import start_session, end_session
from apps.base.encryption import hash_value
from apps.base.mail import send_email

logger = logging.getLogger('apps')


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


INVALID_STUDENT_LOGIN = 'Invalid student ID or password'


class AuthRateThrottle(ScopedRateThrottle):
    scope = 'auth'


class OnboardView(generics.CreateAPIView):
    """Public endpoint for new school registration. Only creates school_admin accounts."""
    serializer_class = OnboardSerializer
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (AuthRateThrottle,)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        try:
            from apps.billing.term_dates import alert_new_school
            alert_new_school(user.school)
        except Exception:                      # the school is created; a failed alert must not undo that
            logger.exception('Could not send the new-school term date alert')
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


PASSWORD_SYMBOLS = '!@#$%&*?'


def generate_password(length=16):
    """A random password that passes the validators: mixed case, a digit and a symbol."""
    alphabet = string.ascii_letters + string.digits + PASSWORD_SYMBOLS
    chars = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice(PASSWORD_SYMBOLS),
    ]
    chars += [secrets.choice(alphabet) for _ in range(max(0, length - len(chars)))]
    secrets.SystemRandom().shuffle(chars)
    return ''.join(chars)


class ChangePasswordView(generics.GenericAPIView):
    """Change your own password. Also clears the must-change flag from a generated one."""
    serializer_class = ChangePasswordSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Password changed. Use the new one next time you sign in.'})


def platform_sign_in():
    """Where a platform admin signs in: the bare domain, not a school subdomain."""
    domain = (getattr(settings, 'PLATFORM_DOMAIN', '') or 'clarriva.com').strip()
    scheme = 'http' if domain == 'localhost' or domain.endswith('.localhost') else 'https'
    return f'{scheme}://{domain}/login'


class AdminGenerateLoginView(generics.GenericAPIView):
    """Super admin makes another admin from an email.

    The login details are emailed to that address, and also come back once, so the
    password can still be handed over when the email could not be sent."""
    serializer_class = GenerateAdminLoginSerializer
    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        email = data['email']

        base = email.split('@')[0][:30] or 'admin'
        username = base
        counter = 1
        while User.objects.filter(username__iexact=username).exists():
            username = f'{base}{counter}'
            counter += 1

        password = generate_password()
        user = User(
            username=username,
            email=email,
            first_name=data.get('first_name', ''),
            last_name=data.get('last_name', ''),
            role='super_admin',
            is_staff=True,
            must_change_password=True,
        )
        user.set_password(password)
        user.save()
        name = f'{user.first_name} {user.last_name}'.strip() or user.email
        emailed = send_email(
            user.email, 'Your Clariva admin login',
            '\n'.join([
                f'Hello {name},', '',
                'An admin account has been created for you on Clariva.', '',
                f'Sign in at: {platform_sign_in()}',
                f'Email: {user.email}',
                f'Password: {password}', '',
                'You will choose your own password the first time you sign in.',
            ]),
        )
        return Response({
            'user': UserSerializer(user).data,
            'email': user.email,
            'password': password,
            'emailed': emailed,
        }, status=status.HTTP_201_CREATED)

class MeView(generics.RetrieveUpdateAPIView):
    def get_serializer_class(self):
        if self.request.method in permissions.SAFE_METHODS:
            return UserSerializer
        return SelfUpdateSerializer

    def get_object(self):
        return self.request.user

    def update(self, request, *args, **kwargs):
        super().update(request, *args, **kwargs)
        return Response(UserSerializer(request.user).data)

class StudentLoginView(generics.GenericAPIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (AuthRateThrottle,)

    def post(self, request):
        student_id = request.data.get('student_id', '').strip()
        password = request.data.get('password', '')
        school_id = request.data.get('school_id')

        if not student_id:
            return Response({'detail': 'Student ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'detail': 'Password is required'}, status=status.HTTP_400_BAD_REQUEST)
        # Admission numbers are unique across the system, so the school is optional.
        # The generated login email or username also works.
        students = User.objects.filter(role='student')
        if school_id:
            students = students.filter(school_id=school_id)
        user = (students.filter(student_profile__admission_no_hash__in=[hash_value(student_id), hash_value(student_id.upper())]).first()
                or students.filter(email__iexact=student_id).first()
                or students.filter(username__iexact=student_id).first())
        if user is None:
            return Response({'detail': INVALID_STUDENT_LOGIN}, status=status.HTTP_400_BAD_REQUEST)

        if not user.is_active or not check_password(password, user.password):
            return Response({'detail': INVALID_STUDENT_LOGIN}, status=status.HTTP_400_BAD_REQUEST)

        sid = start_session(user, request, request.data.get('device_id', ''))
        refresh = RefreshToken.for_user(user)
        refresh['role'] = 'student'
        refresh['school_id'] = str(user.school_id) if user.school_id else None
        if sid:
            refresh['sid'] = sid
        access = refresh.access_token
        access['role'] = 'student'
        access['school_id'] = str(user.school_id) if user.school_id else None
        return Response({
            'access': str(access),
            'refresh': str(refresh),
            'role': 'student',
            'student_name': user.get_full_name(),
            'school_id': str(user.school_id) if user.school_id else None,
        })


class LogoutView(generics.GenericAPIView):
    """Blacklist the supplied refresh token."""
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        from rest_framework_simplejwt.exceptions import TokenError
        try:
            RefreshToken(request.data.get('refresh', '')).blacklist()
        except TokenError:
            pass
        end_session(request.user)          # the student's other tokens stop working too
        return Response(status=status.HTTP_204_NO_CONTENT)


class UserListView(generics.ListAPIView):
    serializer_class = UserSerializer
    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def get_queryset(self):
        return User.objects.select_related('student_profile', 'student_profile__class_group').all()
