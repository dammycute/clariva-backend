from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth.hashers import check_password
from .serializers import RegisterSerializer, UserSerializer
from apps.students.models import Student

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
            student = Student.objects.get(admission_no__iexact=student_id)
        except Student.DoesNotExist:
            return Response({'detail': 'Student ID not found'}, status=status.HTTP_400_BAD_REQUEST)

        if not student.user:
            return Response(
                {'detail': 'No login account exists for this student. Contact your school admin.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not check_password(password, student.user.password):
            return Response({'detail': 'Incorrect password'}, status=status.HTTP_400_BAD_REQUEST)

        refresh = RefreshToken.for_user(student.user)
        refresh['role'] = 'student'
        refresh['school_id'] = str(student.school_id) if student.school_id else None
        refresh.access_token['role'] = 'student'
        refresh.access_token['school_id'] = str(student.school_id) if student.school_id else None
        return Response({
            'access': str(refresh.access_token),
            'refresh': str(refresh),
            'role': 'student',
            'student_name': student.full_name,
            'school_id': str(student.school_id) if student.school_id else None,
        })
