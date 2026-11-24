from rest_framework import serializers

from .models import DemoRequest


class DemoRequestReadSerializer(serializers.ModelSerializer):
    """A demo request as the platform admin sees it (contact details decrypted)."""

    role_label = serializers.CharField(source='get_role_display', read_only=True)

    class Meta:
        model = DemoRequest
        fields = (
            'id', 'name', 'school_name', 'role', 'role_label', 'phone', 'email',
            'students', 'message', 'emailed', 'created_at',
        )
        read_only_fields = fields
