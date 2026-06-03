from rest_framework import serializers, viewsets
from .models import Grade

class GradeSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = Grade
        fields = '__all__'
        read_only_fields = ('school',)

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None

from apps.mixins import SchoolFilterMixin

class GradeViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Grade.objects.select_related('student', 'subject').all()
    serializer_class = GradeSerializer

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
                qs = qs.filter(student__class_group_id__in=teacher_classes)

        student_id = self.request.query_params.get('student_id')
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs
