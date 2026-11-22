import re

from rest_framework import generics, permissions, serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from .models import DemoRequest
from .notify import notify


class DemoRequestSerializer(serializers.ModelSerializer):
    website = serializers.CharField(required=False, allow_blank=True, write_only=True)   # bot trap: people never see it

    class Meta:
        model = DemoRequest
        fields = ('name', 'school_name', 'role', 'phone', 'email', 'students', 'message', 'website')
        extra_kwargs = {'email': {'required': False, 'allow_blank': True},
                        'message': {'max_length': 2000},
                        'students': {'min_value': 1, 'max_value': 100000}}

    def validate_phone(self, value):
        if not re.fullmatch(r'[0-9+\-\s()]{7,20}', value.strip()):
            raise serializers.ValidationError('Enter a phone number we can call or message.')
        return value.strip()

    def validate_email(self, value):
        if value and not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', value):
            raise serializers.ValidationError('Enter a valid email address.')
        return value


class DemoRequestView(generics.CreateAPIView):
    """Public: the landing page's "Request a demo" form."""
    serializer_class = DemoRequestSerializer
    permission_classes = (permissions.AllowAny,)
    authentication_classes = ()                   # an old or replaced sign-in must not block a public form
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = 'demo'

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if serializer.validated_data.pop('website', ''):
            return Response({'received': True}, status=status.HTTP_201_CREATED)   # a bot: look successful, save nothing
        lead = serializer.save()
        if notify(lead):
            DemoRequest.objects.filter(pk=lead.pk).update(emailed=True)
        return Response({'received': True}, status=status.HTTP_201_CREATED)
