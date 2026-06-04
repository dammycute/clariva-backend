from rest_framework import serializers
from .models import GuardianAccount, GuardianStudent


class GuardianAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = GuardianAccount
        fields = ('id', 'school', 'phone', 'pin', 'created_at')
        read_only_fields = ('school', 'created_at')
        extra_kwargs = {'pin': {'write_only': True}}


class GuardianStudentSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    admission_no = serializers.SerializerMethodField()

    class Meta:
        model = GuardianStudent
        fields = ('id', 'guardian', 'student', 'student_name', 'admission_no', 'created_at')
        read_only_fields = ('created_at',)

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else None

    def get_admission_no(self, obj):
        return obj.student.admission_no if obj.student else None
