from rest_framework import serializers

from apps.schools.models import TERM_CHOICES, School
from .models import Payment, TermCalendar


class TermCalendarSerializer(serializers.ModelSerializer):
    state_name = serializers.CharField(source='state.name', read_only=True)
    school_name = serializers.CharField(source='school.name', read_only=True, default=None)

    class Meta:
        model = TermCalendar
        fields = ('id', 'state', 'state_name', 'school', 'school_name', 'academic_year',
                  'term', 'resumes_on', 'provisional', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        attrs = super().validate(attrs)
        state = attrs.get('state', getattr(self.instance, 'state', None))
        school = attrs.get('school', getattr(self.instance, 'school', None))
        year = attrs.get('academic_year', getattr(self.instance, 'academic_year', None))
        term = attrs.get('term', getattr(self.instance, 'term', None))
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
