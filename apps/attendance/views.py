from rest_framework import serializers, viewsets
from .models import Attendance

class AttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = '__all__'
        read_only_fields = ('school',)

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else None

from apps.mixins import SchoolFilterMixin

class AttendanceViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Attendance.objects.select_related('student').all()
    serializer_class = AttendanceSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user

        # Student self-access
        if user.role == 'student':
            return qs.filter(student__user=user)

        # Teacher scoping
        if user.role == 'teacher':
            staff = user.staff_set.first()
            if staff:
                teacher_classes = staff.class_set.values_list('id', flat=True)
                qs = qs.filter(class_group_id__in=teacher_classes)

        class_id = self.request.query_params.get('class_id')
        date = self.request.query_params.get('date')
        student_id = self.request.query_params.get('student_id')
        if class_id:
            qs = qs.filter(class_group_id=class_id)
        if date:
            qs = qs.filter(date=date)
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs
