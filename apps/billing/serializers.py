import re

from rest_framework import serializers

from apps.schools.models import TERM_CHOICES, School
from .models import Payment, TermCalendar


class TermCalendarSerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source='state.name', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True, default=None)
    confirmed_by_name = serializers.SerializerMethodField()

    class Meta:
        model = TermCalendar
        fields = ('id', 'state', 'state_name', 'school', 'school_name', 'academic_year',
                  'term', 'resumes_on', 'provisional', 'source_url', 'confirmed_by_name',
                  'confirmed_at', 'created_at', 'updated_at')
        read_only_fields = ('id', 'confirmed_at', 'created_at', 'updated_at')
        validators = []                  # uniqueness is checked below, with a clearer message

    def get_confirmed_by_name(self, obj):
        user = obj.confirmed_by
        return (user.get_full_name() or user.email) if user else None

    def validate_academic_year(self, value):
        match = re.fullmatch(r'(\d{4})/(\d{4})', str(value).strip())
        if not match or int(match.group(2)) != int(match.group(1)) + 1:
            raise serializers.ValidationError('Write the academic year like 2026/2027.')
        return value.strip()

    def validate(self, attrs):
        attrs = super().validate(attrs)
        state = attrs.get('state', getattr(self.instance, 'state', None))
        school = attrs.get('school', getattr(self.instance, 'school', None))
        year = attrs.get('academic_year', getattr(self.instance, 'academic_year', None))
        term = attrs.get('term', getattr(self.instance, 'term', None))
        # A confirmed date needs the state's notice as proof.
        provisional = attrs.get('provisional', getattr(self.instance, 'provisional', False))
        if not provisional and not attrs.get('source_url', getattr(self.instance, 'source_url', '')):
            raise serializers.ValidationError({'source_url': (
                'Paste the link to the official notice, or mark the date as provisional.')})
        clash = TermCalendar.objects.filter(
            state=state, school=school, academic_year=year, term=term,
        )
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                'That term already has a date for this state and school. Edit the existing one.'
            )
        return attrs


class PaymentSerializer(serializers.ModelSerializer):
    school_name = serializers.CharField(source='school.name', read_only=True)

    class Meta:
        model = Payment
        fields = ('id', 'school', 'school_name', 'reference', 'provider', 'kind', 'status',
                  'amount', 'blocks_after', 'students_at_payment', 'academic_year', 'term',
                  'covers_from', 'access_until', 'channel', 'paid_at', 'note', 'created_at')
        read_only_fields = fields


class ManualPaymentSerializer(serializers.Serializer):
    """A payment the super admin enters by hand: a grant, an extension, or a transfer."""

    school = serializers.PrimaryKeyRelatedField(queryset=School.objects.all())
    academic_year = serializers.CharField(required=False, allow_blank=True, max_length=20)
    term = serializers.ChoiceField(choices=[c[0] for c in TERM_CHOICES], required=False)
    students = serializers.IntegerField(required=False, min_value=1)
    access_until = serializers.DateField(required=False)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)
