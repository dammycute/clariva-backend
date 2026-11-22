import re
from datetime import date

from django.db import transaction
from rest_framework import serializers

from apps.accounts.models import User
from apps.base.encryption import hash_value
from apps.classes.models import Class
from apps.fees.services import FeeService
from .models import StudentProfile

# Fields that live on the profile, not the user. They are read from the request and saved there.
PROFILE_FIELDS = ('admission_no', 'class_group', 'guardian_name', 'guardian_phone',
                  'guardian_email', 'student_status', 'academic_year')
STUDENT_STATUSES = ('active', 'inactive', 'graduated', 'transferred', 'withdrawn', 'suspended')


def has_login(user):
    """True when the student has a real password (not empty, not the unusable marker)."""
    return bool(user.password) and user.has_usable_password()


def sanitize_admission(admission_no):
    return re.sub(r'[^a-z0-9]+', '-', str(admission_no).lower()).strip('-')


def next_admission_no(school):
    """CLR/<year>/<5 digits>, the next one nobody has used."""
    year = date.today().year
    seq = StudentProfile.objects.filter(school=school).count() + 1
    while True:
        candidate = f'CLR/{year}/{seq:05d}'
        if not StudentProfile.objects.filter(admission_no=candidate).exists():
            return candidate
        seq += 1


def unique_username(admission_no):
    base = f'student.{sanitize_admission(admission_no)}'
    username, n = base, 1
    while User.objects.filter(username=username).exists():
        username = f'{base}{n}'
        n += 1
    return username


class StudentSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()
    admission_no = serializers.SerializerMethodField()
    class_group = serializers.SerializerMethodField()
    guardian_name = serializers.SerializerMethodField()
    guardian_phone = serializers.SerializerMethodField()
    guardian_email = serializers.SerializerMethodField()
    student_status = serializers.SerializerMethodField()
    academic_year = serializers.SerializerMethodField()
    has_account = serializers.SerializerMethodField()
    user_email = serializers.SerializerMethodField()
    signed_in_on = serializers.SerializerMethodField()
    signed_in_at = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'first_name', 'last_name', 'phone', 'role',
            'is_active', 'school', 'school_id', 'avatar_url', 'photo_url',
            'date_of_birth', 'gender', 'lga_of_origin', 'state_of_origin',
            'admission_no', 'class_group', 'class_name', 'guardian_name',
            'guardian_phone', 'guardian_email', 'student_status', 'academic_year',
            'has_account', 'user_email', 'signed_in_on', 'signed_in_at',
        )
        # username and email are made by the server; school is set from the signed-in admin.
        read_only_fields = ('school', 'school_id', 'role', 'username', 'email')

    def _profile(self, obj):
        return getattr(obj, 'student_profile', None)

    def get_signed_in_on(self, obj):
        """The device the student is signed in on, such as 'Chrome on Android', or None."""
        return obj.session_device or None

    def get_signed_in_at(self, obj):
        return obj.session_started_at.isoformat() if obj.session_started_at else None

    def get_class_name(self, obj):
        sp = self._profile(obj)
        return sp.class_group.name if sp and sp.class_group else None

    def get_admission_no(self, obj):
        sp = self._profile(obj)
        return sp.admission_no if sp else None

    def get_class_group(self, obj):
        sp = self._profile(obj)
        return str(sp.class_group_id) if sp and sp.class_group_id else None

    def get_guardian_name(self, obj):
        sp = self._profile(obj)
        return sp.guardian_name if sp else None

    def get_guardian_phone(self, obj):
        sp = self._profile(obj)
        return sp.guardian_phone if sp else None

    def get_guardian_email(self, obj):
        sp = self._profile(obj)
        return sp.guardian_email if sp else None

    def get_student_status(self, obj):
        sp = self._profile(obj)
        return sp.student_status if sp else None

    def get_academic_year(self, obj):
        sp = self._profile(obj)
        return sp.academic_year if sp else None

    def get_has_account(self, obj):
        return has_login(obj)

    def get_user_email(self, obj):
        return obj.email or None

    # ---- writing the profile fields ----

    def _profile_input(self, school):
        """Pick the profile fields out of the request, checked and cleaned."""
        raw = getattr(self, 'initial_data', {}) or {}
        out, errors = {}, {}
        for key in PROFILE_FIELDS:
            if key not in raw:
                continue
            val = raw[key]
            val = None if val is None or str(val).strip() == '' else str(val).strip()
            if key == 'class_group':
                if val is not None:
                    if not Class.objects.filter(pk=val, school=school).exists():
                        errors[key] = 'Choose a class from your school.'
                        continue
                out['class_group_id'] = val
            elif key == 'student_status':
                if val is not None and val not in STUDENT_STATUSES:
                    errors[key] = 'Not a valid status.'
                    continue
                out[key] = val or 'active'
            elif key == 'admission_no':
                if val is not None and StudentProfile.objects.filter(admission_no=val).exclude(
                        user_id=getattr(self.instance, 'pk', None)).exists():
                    errors[key] = 'This admission number is already used.'
                    continue
                out[key] = val
            else:
                out[key] = val
        if errors:
            raise serializers.ValidationError(errors)
        return out

    def _save_profile(self, user, data):
        profile, _ = StudentProfile.objects.get_or_create(user=user, defaults={'school': user.school})
        if profile.school_id is None:
            profile.school = user.school
        for key, val in data.items():
            if key == 'admission_no':
                if val and val != profile.admission_no:
                    profile.admission_no = val
                    profile.admission_no_hash = hash_value(val)
                continue
            setattr(profile, key, val)
        if not profile.admission_no:
            profile.admission_no = next_admission_no(user.school)
            profile.admission_no_hash = hash_value(profile.admission_no)
        profile.save()
        FeeService.invoice_student(user)

    @transaction.atomic
    def create(self, validated_data):
        school = validated_data.get('school')
        data = self._profile_input(school)
        adm = data.get('admission_no') or next_admission_no(school)
        data['admission_no'] = adm
        validated_data['username'] = unique_username(adm)
        validated_data['role'] = 'student'
        user = User(**validated_data)
        user.set_unusable_password()
        user.save()
        self._save_profile(user, data)
        return user

    @transaction.atomic
    def update(self, instance, validated_data):
        data = self._profile_input(instance.school)
        instance = super().update(instance, validated_data)
        self._save_profile(instance, data)
        return instance
