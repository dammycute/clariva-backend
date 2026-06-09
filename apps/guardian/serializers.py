from rest_framework import serializers
from .models import GuardianStudent


class GuardianStudentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    admission_no = serializers.SerializerMethodField()

    class Meta:
        model = GuardianStudent
        fields = ('id', 'guardian', 'student', 'student_name', 'admission_no', 'created_at')
        read_only_fields = ('created_at',)

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student else None

    def get_admission_no(self, obj):
        return obj.student.admission_no if obj.student else None
