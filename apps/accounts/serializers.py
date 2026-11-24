from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import User
from .sessions import start_session


class EmailTokenObtainPairSerializer(TokenObtainPairSerializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('username', None)
        self.fields['email'] = serializers.CharField()

    def validate(self, attrs):
        attrs['username'] = attrs.pop('email')
        data = super().validate(attrs)
        user = self.user
        request = self.context.get('request')
        device_id = request.data.get('device_id', '') if request is not None else ''
        if start_session(user, request, device_id):
            # the tokens were made before the session existed; make them again so they carry it
            refresh = self.get_token(user)
            data['refresh'] = str(refresh)
            data['access'] = str(refresh.access_token)
        data['role'] = user.role
        data['school_id'] = str(user.school_id) if user.school_id else None
        data['must_change_password'] = user.must_change_password
        return data

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        token['role'] = user.role
        token['school_id'] = str(user.school_id) if user.school_id else None
        if user.role == 'student' and user.active_session_id:
            token['sid'] = str(user.active_session_id)
        return token


class OnboardSerializer(serializers.ModelSerializer):
    """Public endpoint for new school registration. Creates user + school atomically."""
    password = serializers.CharField(write_only=True, min_length=8, validators=[validate_password])
    username = serializers.CharField(required=False)
    email = serializers.EmailField(required=True)
    school_name = serializers.CharField(max_length=255, write_only=True)
    school_subdomain = serializers.CharField(max_length=50, write_only=True)
    school_type = serializers.CharField(max_length=100, write_only=True, required=False, allow_blank=True)
    school_address = serializers.CharField(max_length=500, write_only=True, required=False, allow_blank=True)
    school_state = serializers.CharField(max_length=100, write_only=True, required=False, allow_blank=True)
    school_lga = serializers.CharField(max_length=100, write_only=True, required=False, allow_blank=True)
    # How many students the school has. It is the first quote, before any student is added.
    school_students = serializers.IntegerField(write_only=True, min_value=1, max_value=100000)

    class Meta:
        model = User
        fields = ('username', 'email', 'password', 'first_name', 'last_name', 'phone',
                  'school_name', 'school_subdomain', 'school_type', 'school_address',
                  'school_state', 'school_lga', 'school_students')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value

    def validate_school_subdomain(self, value):
        from apps.schools.models import School
        slug = value.lower().strip()
        if School.objects.filter(subdomain=slug).exists():
            raise serializers.ValidationError('This subdomain is already taken.')
        return slug

    def validate_school_state(self, value):
        """The state must come from the list the app already has, so billing can find its calendar."""
        from apps.locations.models import State
        name = (value or '').strip()
        if not name or not State.objects.exists():
            return name
        match = State.objects.filter(name__iexact=name).first()
        if match is None:
            raise serializers.ValidationError('Choose a state from the list.')
        return match.name

    def create(self, validated_data):
        from apps.schools.models import School

        # Every school pays online first: no trial, no free period. Until it pays, it is
        # `pending` and sees only its billing page.
        school_data = {
            'name': validated_data.pop('school_name'),
            'subdomain': validated_data.pop('school_subdomain'),
            'school_type': validated_data.pop('school_type', '') or '',
            'address': validated_data.pop('school_address', '') or '',
            'state': validated_data.pop('school_state', '') or '',
            'lga': validated_data.pop('school_lga', '') or '',
            'proprietor_name': f"{validated_data.get('first_name', '')} {validated_data.get('last_name', '')}".strip(),
            'proprietor_phone': validated_data.get('phone', '') or '',
            'declared_students': validated_data.pop('school_students', 0),
            'status': 'pending',
            'plan': 'basic',
            'trial_ends_at': None,
        }

        school = School.objects.create(**school_data)

        password = validated_data.pop('password')
        username = validated_data.pop('username', None) or validated_data.get('email', '').split('@')[0]
        base = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f'{base}{counter}'
            counter += 1
        validated_data['username'] = username
        validated_data['role'] = 'school_admin'
        validated_data['school'] = school
        user = User(**validated_data)
        user.set_password(password)
        user.save()

        return user


class AdminCreateUserSerializer(serializers.ModelSerializer):
    """Admin-only endpoint for creating users with any role."""
    password = serializers.CharField(write_only=True, min_length=8, validators=[validate_password])
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
            if value == 'school_admin' and caller_role != 'super_admin':
                raise serializers.ValidationError('Only super_admin can create school_admin accounts.')
            if caller_role == 'school_admin' and value not in ('teacher', 'student', 'parent', 'bursary'):
                raise serializers.ValidationError('School admins can only create teacher, student, parent, or bursary accounts.')
        return value

    def validate_school(self, value):
        request = self.context.get('request')
        if request and request.user and request.user.role == 'school_admin':
            if value and value.pk != request.user.school_id:
                raise serializers.ValidationError('You can only create accounts in your own school.')
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


class SelfUpdateSerializer(serializers.ModelSerializer):
    """Fields a user may change on their own account."""
    class Meta:
        model = User
        fields = ('first_name', 'last_name', 'phone', 'avatar_url', 'photo_url')


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
            'is_active', 'must_change_password', 'school', 'school_id', 'avatar_url', 'photo_url',
            'date_of_birth', 'gender', 'lga_of_origin', 'state_of_origin',
            'admission_no', 'class_group', 'class_name', 'guardian_name',
            'guardian_phone', 'guardian_email', 'student_status', 'academic_year',
        )
        read_only_fields = (
            'id', 'username', 'email', 'role', 'is_active', 'must_change_password', 'school', 'school_id',
        )

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


class ChangePasswordSerializer(serializers.Serializer):
    """A signed-in user setting their own password, old one first."""

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        if not self.context['request'].user.check_password(value):
            raise serializers.ValidationError('That is not your current password.')
        return value

    def validate_new_password(self, value):
        user = self.context['request'].user
        validate_password(value, user)
        if user.check_password(value):
            raise serializers.ValidationError('Choose a password you have not used here before.')
        return value

    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.must_change_password = False
        user.save(update_fields=['password', 'must_change_password'])
        return user


class GenerateAdminLoginSerializer(serializers.Serializer):
    """A new platform admin, made from an email address. The server makes the password."""

    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True, max_length=150)
    last_name = serializers.CharField(required=False, allow_blank=True, max_length=150)

    def validate_email(self, value):
        value = value.strip().lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError('A user with this email already exists.')
        return value
