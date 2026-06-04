from rest_framework import serializers
from .models import Student, StudentAccessCode

class StudentSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()
    has_account = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    access_code = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = '__all__'
        read_only_fields = ('school', 'has_account', 'user_email', 'access_code')

    def get_class_name(self, obj):
        return obj.class_group.name if obj.class_group else None

    def get_has_account(self, obj):
        return obj.user_id is not None

    def get_user_email(self, obj):
        return obj.user.email if obj.user else None

    def get_access_code(self, obj):
        try:
            return obj.access_code_link.code
        except StudentAccessCode.DoesNotExist:
            return None
