from rest_framework import serializers, viewsets
from apps.mixins import SchoolFilterMixin
from .models import ActivityLog

class ActivityLogSerializer(serializers.ModelSerializer):
    user_name = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = '__all__'
        read_only_fields = ('school', 'user', 'user_name')

    def get_user_name(self, obj):
        if obj.user:
            return obj.user.get_full_name() or obj.user.email
        return None

class ActivityLogViewSet(SchoolFilterMixin, viewsets.ReadOnlyModelViewSet):
    queryset = ActivityLog.objects.select_related('user', 'school').all()
    serializer_class = ActivityLogSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        action = self.request.query_params.get('action')
        model = self.request.query_params.get('model')
        search = self.request.query_params.get('search')
        if action:
            qs = qs.filter(action=action)
        if model:
            qs = qs.filter(model_name__icontains=model)
        if search:
            qs = qs.filter(object_repr__icontains=search) | qs.filter(model_name__icontains=search)
        return qs
