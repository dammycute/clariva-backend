import uuid

from rest_framework import serializers

from apps.accounts.models import User
from apps.classes.models import Class
from .models import Staff


class StaffSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    has_account = serializers.SerializerMethodField()
    user_id = serializers.UUIDField(source='user.id', read_only=True)
    first_name = serializers.CharField(write_only=True, required=False)
    last_name = serializers.CharField(write_only=True, required=False)
    user_phone = serializers.CharField(write_only=True, required=False)
    user_email = serializers.EmailField(write_only=True, required=True)
    form_classes = serializers.SerializerMethodField()

    class Meta:
        model = Staff
        fields = '__all__'
        read_only_fields = ('school', 'user')

    def get_full_name(self, obj):
        return obj.user.get_full_name() if obj.user else None

    def get_phone(self, obj):
        return obj.user.phone if obj.user else None

    def get_email(self, obj):
        return obj.user.email if obj.user else None

    def get_has_account(self, obj):
        return obj.user_id is not None and obj.user.has_usable_password()

    def get_form_classes(self, obj):
        if not obj.user_id:
            return []
        return [{'id': str(c.id), 'name': c.name} for c in Class.objects.filter(form_teacher=obj.user)]

    @staticmethod
    def _map_role(staff_role: str) -> str:
        mapping = {
            'PRINCIPAL': 'principal',
            'VICE PRINCIPAL': 'teacher',
            'HEAD OF DEPARTMENT': 'teacher',
            'ADMIN': 'school_admin',
            'ACCOUNTANT': 'bursary',
            'BURSAR': 'bursary',
        }
        return mapping.get(staff_role.strip().upper(), 'teacher')

    def create(self, validated_data):
        first_name = validated_data.pop('first_name', '')
        last_name = validated_data.pop('last_name', '')
        user_email = validated_data.pop('user_email', '')
        user_phone = validated_data.pop('user_phone', '')
        school = validated_data.get('school')

        username = f'staff_{uuid.uuid4().hex[:12]}'
        user = User.objects.create_user(
            username=username,
            first_name=first_name or '',
            last_name=last_name or '',
            email=user_email or '',
            phone=user_phone or '',
            role=self._map_role(validated_data.get('role', 'Teacher')),
            school=school,
        )

        staff = Staff.objects.create(user=user, **validated_data)
        return staff

    def update(self, instance, validated_data):
        first_name = validated_data.pop('first_name', None)
        last_name = validated_data.pop('last_name', None)
        validated_data.pop('user_email', None)
        validated_data.pop('user_phone', None)
        validated_data.pop('email', None)
        validated_data.pop('phone', None)
        validated_data.pop('user', None)

        if instance.user:
            changed = False
            if first_name is not None and instance.user.first_name != first_name:
                instance.user.first_name = first_name
                changed = True
            if last_name is not None and instance.user.last_name != last_name:
                instance.user.last_name = last_name
                changed = True
            if changed:
                instance.user.save(update_fields=['first_name', 'last_name'])

        return super().update(instance, validated_data)
