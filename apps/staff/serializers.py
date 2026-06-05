from rest_framework import serializers
from .models import Staff

class StaffSerializer(serializers.ModelSerializer):
    has_account = serializers.SerializerMethodField()
    form_classes = serializers.SerializerMethodField()

    class Meta:
        model = Staff
        fields = '__all__'
        read_only_fields = ('school', 'has_account')

    def get_has_account(self, obj):
        return obj.user_id is not None

    def get_form_classes(self, obj):
        return list(obj.class_set.values('id', 'name'))
