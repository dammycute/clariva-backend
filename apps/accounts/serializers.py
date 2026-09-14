from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('username', None)
        self.fields['email'] = serializers.CharField()

    def validate(self, attrs):
        attrs['username'] = attrs.pop('email')
        data = super().validate(attrs)
        user = self.user
        data['role'] = user.role
        data['school_id'] = str(user.school_id) if user.school_id else None
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['school_id'] = str(user.school_id) if user.school_id else None
        return token


class OnboardSerializer(serializers.ModelSerializer):
    """Public endpoint for new school registration. Only allows school_admin role."""
    password = serializers.CharField(write_only=True, min_length=8)
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'first_name', 'last_name', 'phone')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        username = validated_data.pop('username', None) or validated_data.get('email', '').split('@')[0]
        base = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1
        validated_data['username'] = username
        validated_data['role'] = 'school_admin'
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class AdminCreateUserSerializer(serializers.ModelSerializer):
    """Admin-only endpoint for creating users with any role."""
    password = serializers.CharField(write_only=True, min_length=8)
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=True)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'first_name', 'last_name', 'phone', 'role', 'school')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_role(self, value):
        request = self.context.get('request')
        if request and request.user:
            caller_role = request.user.role
            if value == 'super_admin' and caller_role != 'super_admin':
                raise serializers.ValidationError('Only super_admin can create super_admin accounts.')
            if value == 'school_admin' and caller_role not in ('super_admin', 'school_admin'):
                raise serializers.ValidationError('Insufficient permissions to create this role.')
        return value

    def create(self, validated_data):
        password = validated_data.pop('password')
        username = validated_data.pop('username', None) or validated_data.get('email', '').split('@')[0]
        base = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1
        validated_data['username'] = username
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserSerializer(serializers.ModelSerializer):
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
        read_only_fields = ('school_id',)

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
