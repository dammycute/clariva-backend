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


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    username = serializers.CharField(required=False)
    email = serializers.CharField(required=False)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'first_name', 'last_name', 'phone', 'role')

    def validate_username(self, value):
        if not value:
            return None
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
        from apps.schools.models import School
        role = validated_data.get('role', 'school_admin')
        if role != 'super_admin' and not validated_data.get('school'):
            school = School.objects.first()
            if school:
                validated_data['school'] = school
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        return user


class UserSerializer(serializers.ModelSerializer):
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
        read_only_fields = ('school_id', 'access_code')

    def get_class_name(self, obj):
        return obj.class_group.name if obj.class_group else None

    def get_access_code(self, obj):
        if obj.role != 'student':
            return None
        try:
            return obj.access_code_link.code
        except User.access_code_link.RelatedObjectDoesNotExist:
            return None
