from rest_framework import serializers
from apps.accounts.models import User, StudentAccessCode


class StudentSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()
    access_code = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'phone', 'role',
            'is_active', 'school', 'school_id', 'avatar_url', 'photo_url',
            'date_of_birth', 'gender', 'lga_of_origin', 'state_of_origin',
            'admission_no', 'class_group', 'class_name', 'guardian_name',
            'guardian_phone', 'guardian_email', 'student_status', 'academic_year',
            'access_code',
        )
        read_only_fields = ('school_id', 'access_code', 'role')

    def get_class_name(self, obj):
        return obj.class_group.name if obj.class_group else None

    def get_access_code(self, obj):
        try:
            return obj.access_code_link.code
        except User.access_code_link.RelatedObjectDoesNotExist:
            return None
