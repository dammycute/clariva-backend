import re

from django.conf import settings
from rest_framework import serializers
from .models import School, GradingConfig, DEFAULT_GRADE_BOUNDARIES

# Names that can never belong to a school: they are the product's own addresses.
RESERVED_SUBDOMAINS = {
    'www', 'app', 'api', 'admin', 'portal', 'dashboard', 'login', 'signup',
    'mail', 'smtp', 'ftp', 'cdn', 'static', 'assets', 'docs', 'help', 'support',
    'status', 'billing', 'pay', 'payments', 'school', 'schools', 'clariva',
}


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

    def get_portal_url(self, obj):
        domain = (getattr(settings, 'PLATFORM_DOMAIN', '') or '').strip()
        return f'https://{obj.subdomain}.{domain}' if domain and obj.subdomain else ''

    def validate_subdomain(self, value):
        """A subdomain is one DNS label: lowercase letters, digits and dashes."""
        clean = re.sub(r'[^a-z0-9-]+', '-', str(value or '').strip().lower()).strip('-')
        if not clean:
            raise serializers.ValidationError(
                'Choose a short name for the school address, such as queens-college.'
            )
        if clean in RESERVED_SUBDOMAINS:
            raise serializers.ValidationError('That name is reserved. Choose another.')
        return clean
