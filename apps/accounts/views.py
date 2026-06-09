from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import check_password
from .serializers import RegisterSerializer, UserSerializer
from .models import User

class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny,)

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

        if not student_id:
            return Response({'detail': 'Student ID is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not password:
            return Response({'detail': 'Password is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(admission_no__iexact=student_id, role='student')
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
