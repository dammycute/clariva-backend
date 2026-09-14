from rest_framework import viewsets
from .models import Attendance
from .serializers import AttendanceSerializer
from apps.mixins import SchoolFilterMixin


class AttendanceViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Attendance.objects.select_related('student').all()
    serializer_class = AttendanceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        if user.role == 'student':
            return qs.filter(student=user)

        if user.role == 'teacher':
            teacher_classes = user.class_set.values_list('id', flat=True)
            if teacher_classes:
                qs = qs.filter(student__student_profile__class_group_id__in=teacher_classes)

        class_id = self.request.query_params.get('class_id')
        date = self.request.query_params.get('date')
        student_id = self.request.query_params.get('student_id')
        if class_id:
            qs = qs.filter(student__student_profile__class_group_id=class_id)
        if date:
            qs = qs.filter(date=date)
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs
