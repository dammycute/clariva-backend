from rest_framework import serializers
from apps.accounts.models import User
from .models import StudentProfile


class StudentSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()
    admission_no = serializers.SerializerMethodField()
    class_group = serializers.SerializerMethodField()
    guardian_name = serializers.SerializerMethodField()
    guardian_phone = serializers.SerializerMethodField()
    guardian_email = serializers.SerializerMethodField()
    student_status = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'phone', 'role',
            'is_active', 'school', 'school_id', 'avatar_url', 'photo_url',
            'date_of_birth', 'gender', 'lga_of_origin', 'state_of_origin',
            'admission_no', 'class_group', 'class_name', 'guardian_name',
            'guardian_phone', 'guardian_email', 'student_status', 'academic_year',
        )
        read_only_fields = ('school_id', 'role')

    def get_class_name(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return sp.class_group.name if sp and sp.class_group else None

    def get_admission_no(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return sp.admission_no if sp else None

    def get_class_group(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return str(sp.class_group_id) if sp and sp.class_group_id else None

    def get_guardian_name(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return sp.guardian_name if sp else None

    def get_guardian_phone(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return sp.guardian_phone if sp else None

    def get_guardian_email(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return sp.guardian_email if sp else None

    def get_student_status(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return sp.student_status if sp else None

    def get_academic_year(self, obj):
        sp = getattr(obj, 'student_profile', None)
        return sp.academic_year if sp else None
