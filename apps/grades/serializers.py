from rest_framework import serializers
from .models import Grade


class GradeSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    subject_name = serializers.SerializerMethodField()

    class Meta:
        model = Grade
        fields = [
            'id', 'school', 'student', 'subject', 'term', 'academic_year',
            'ca1', 'ca2', 'assignment', 'exam', 'total', 'grade',
            'results_status', 'submitted_by', 'submitted_at',
            'approved_by', 'approved_at', 'rejection_note', 'created_at',
            'student_name', 'subject_name',
        ]
        read_only_fields = ('school', 'total', 'results_status', 'submitted_by', 'submitted_at', 'approved_by', 'approved_at')

    def get_student_name(self, obj):
        return obj.student.get_full_name() if obj.student else None

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None
