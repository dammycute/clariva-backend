from rest_framework import serializers
from apps.exams.models import ReportCard


class ReportCardSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    class_name = serializers.SerializerMethodField()

    class Meta:
        model = ReportCard
        fields = '__all__'
        read_only_fields = ('school',)

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student else None

    def get_class_name(self, obj):
        sp = getattr(obj.student, 'student_profile', None) if obj.student else None
        return sp.class_group.name if sp and sp.class_group else None
