from rest_framework import serializers
from .models import Class

class ClassSerializer(serializers.ModelSerializer):
    form_teacher_name = serializers.SerializerMethodField()

    class Meta:
        model = Class
        fields = '__all__'
        read_only_fields = ('school',)

    def get_form_teacher_name(self, obj):
        if obj.form_teacher:
            return obj.form_teacher.get_full_name()
        return None
