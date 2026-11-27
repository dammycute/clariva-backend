import re

from django.conf import settings
from rest_framework import serializers
from .models import School, GradingConfig, DEFAULT_GRADE_BOUNDARIES

# Names that can never belong to a school: they are the product's own addresses.
RESERVED_SUBDOMAINS = {
    'www', 'app', 'api', 'admin', 'portal', 'dashboard', 'login', 'signup',
    'mail', 'smtp', 'ftp', 'cdn', 'static', 'assets', 'docs', 'help', 'support',
    'status', 'billing', 'pay', 'payments', 'school', 'schools', 'clariva', 'clarriva',
    'test', 'api-test', 'staging', 'dev',
}

# What a school's own admins may change. Billing, status, the address and the state
# (which decides the billing calendar) stay with the platform admin.
SCHOOL_ADMIN_EDITABLE = {
    'name', 'logo_url', 'accent_color', 'address', 'lga', 'school_type', 'proprietor_name',
    'proprietor_phone', 'current_term', 'current_academic_year', 'single_device_students',
}


def clean_subdomain(value, exclude_pk=None):
    """A subdomain is one DNS label: lowercase letters, digits and dashes, not reserved, not taken."""
    clean = re.sub(r'[^a-z0-9-]+', '-', str(value or '').strip().lower()).strip('-')[:50].strip('-')
    if not clean:
        raise serializers.ValidationError('Choose a short name for the school address, such as queens-college.')
    if clean in RESERVED_SUBDOMAINS:
        raise serializers.ValidationError('That name is reserved. Choose another.')
    if School.objects.filter(subdomain__iexact=clean).exclude(pk=exclude_pk).exists():
        raise serializers.ValidationError('This subdomain is already taken.')
    return clean


class GradingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradingConfig
        fields = '__all__'
        read_only_fields = ('school',)


class SchoolSerializer(serializers.ModelSerializer):
    grading_config = GradingConfigSerializer(read_only=True)
    portal_url = serializers.SerializerMethodField()

    class Meta:
        model = School
        fields = '__all__'

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        if request is not None and getattr(request.user, 'role', None) != 'super_admin':
            # The settings page sends the whole record back, so other fields are ignored, not refused.
            for name, field in fields.items():
                if name not in SCHOOL_ADMIN_EDITABLE:
                    field.read_only = True
                    field.required = False
                    field.validators = []
        return fields

    def get_portal_url(self, obj):
        domain = (getattr(settings, 'PLATFORM_DOMAIN', '') or '').strip()
        return f'https://{obj.subdomain}.{domain}' if domain and obj.subdomain else ''

    def validate_subdomain(self, value):
        if self.instance is not None and value == self.instance.subdomain:
            return value                              # an older address that is not being changed
        return clean_subdomain(value, exclude_pk=getattr(self.instance, 'pk', None))
