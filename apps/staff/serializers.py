import uuid

from rest_framework import serializers

from apps.accounts.models import User
from apps.classes.models import Class
from .models import TeacherProfile, StaffProfile


class StaffSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    has_account = serializers.SerializerMethodField()
    user_id = serializers.UUIDField(source='id', read_only=True)
    first_name = serializers.CharField(write_only=True, required=False)
    last_name = serializers.CharField(write_only=True, required=False)
    user_phone = serializers.CharField(write_only=True, required=False, allow_blank=True)
    user_email = serializers.EmailField(write_only=True, required=False, allow_blank=True)
    form_classes = serializers.SerializerMethodField()
    qualification = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    date_joined = serializers.DateField(write_only=True, required=False, allow_null=True)
    status = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    role = serializers.CharField(source='get_role_display', read_only=True)
    staff_role = serializers.CharField(write_only=True, required=False)
    subjects = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = User
        fields = (
            'id', 'user_id', 'username', 'email', 'first_name', 'last_name',
            'phone', 'role', 'staff_role', 'qualification', 'subjects', 'date_joined',
            'status', 'has_account', 'full_name', 'user_phone', 'user_email',
            'form_classes', 'school',
        )
        read_only_fields = ('school', 'user', 'id', 'user_id', 'username')

    def validate_user_email(self, value):
        if not value:
            return value
        qs = User.objects.filter(email=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def get_full_name(self, obj):
        return obj.get_full_name()

    def get_phone(self, obj):
        return obj.phone

    def get_email(self, obj):
        return obj.email

    def get_has_account(self, obj):
        return obj.has_usable_password()

    def get_form_classes(self, obj):
        return [{'id': str(c.id), 'name': c.name} for c in Class.objects.filter(form_teacher=obj)]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        if instance.role == 'teacher':
            profile = getattr(instance, 'teacher_profile', None)
        else:
            profile = getattr(instance, 'staff_profile', None)
        ret['qualification'] = profile.qualification if profile else None
        ret['status'] = profile.status if profile else None
        ret['date_joined'] = profile.date_joined if profile else None
        ret['subjects'] = (
            [s.strip() for s in profile.subjects.split(',') if s.strip()]
            if profile and profile.subjects else []
        )
        return ret

    @staticmethod
    def _map_role(staff_role: str) -> str:
        mapping = {
            'PRINCIPAL': 'principal',
            'VICE PRINCIPAL': 'teacher',
            'HEAD OF DEPARTMENT': 'teacher',
            'ADMIN': 'school_admin',
            'ACCOUNTANT': 'bursary',
            'BURSAR': 'bursary',
            'ADMIN OFFICER': 'admin_officer',
        }
        return mapping.get(staff_role.strip().upper(), 'teacher')

    def create(self, validated_data):
        first_name = validated_data.pop('first_name', '')
        last_name = validated_data.pop('last_name', '')
        user_email = validated_data.pop('user_email', '')
        user_phone = validated_data.pop('user_phone', '')
        staff_role = validated_data.pop('staff_role', None)
        qualification = validated_data.pop('qualification', None)
        subjects = validated_data.pop('subjects', '')
        date_joined = validated_data.pop('date_joined', None)
        status = validated_data.pop('status', 'active')
        school = validated_data.get('school')
        profile_role = self._map_role(staff_role) if staff_role else 'teacher'

        username = f'staff_{uuid.uuid4().hex[:12]}'
        user = User.objects.create_user(
            username=username,
            first_name=first_name or '',
            last_name=last_name or '',
            email=user_email or '',
            phone=user_phone or '',
            role=profile_role,
            school=school,
        )

        if profile_role == 'teacher':
            TeacherProfile.objects.create(
                user=user, school=school,
                qualification=qualification,
                subjects=subjects,
                date_joined=date_joined,
                status=status,
            )
        else:
            StaffProfile.objects.create(
                user=user, school=school,
                qualification=qualification,
                subjects=subjects,
                date_joined=date_joined,
                status=status,
            )
        return user

    def update(self, instance, validated_data):
        first_name = validated_data.pop('first_name', None)
        last_name = validated_data.pop('last_name', None)
        user_email = validated_data.pop('user_email', None)
        user_phone = validated_data.pop('user_phone', None)
        validated_data.pop('email', None)
        validated_data.pop('phone', None)
        validated_data.pop('staff_role', None)
        qualification = validated_data.pop('qualification', None)
        subjects = validated_data.pop('subjects', None)
        date_joined = validated_data.pop('date_joined', None)
        status = validated_data.pop('status', None)

        update_fields = []
        if first_name is not None and instance.first_name != first_name:
            instance.first_name = first_name
            update_fields.append('first_name')
        if last_name is not None and instance.last_name != last_name:
            instance.last_name = last_name
            update_fields.append('last_name')
        if user_phone is not None and instance.phone != user_phone:
            instance.phone = user_phone
            update_fields.append('phone')
        if user_email and instance.email != user_email:
            instance.email = user_email
            update_fields.append('email')
        if update_fields:
            instance.save(update_fields=update_fields)

        if instance.role == 'teacher':
            tp = getattr(instance, 'teacher_profile', None)
            if tp:
                if qualification is not None:
                    tp.qualification = qualification
                if subjects is not None:
                    tp.subjects = subjects
                if date_joined is not None:
                    tp.date_joined = date_joined
                if status is not None:
                    tp.status = status
                tp.save()
        else:
            sp = getattr(instance, 'staff_profile', None)
            if sp:
                if qualification is not None:
                    sp.qualification = qualification
                if subjects is not None:
                    sp.subjects = subjects
                if date_joined is not None:
                    sp.date_joined = date_joined
                if status is not None:
                    sp.status = status
                sp.save()

        return instance
