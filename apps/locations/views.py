from rest_framework import viewsets, permissions
from .models import State, LGA
from .serializers import StateSerializer, LGASerializer

class StateViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = State.objects.all()
    serializer_class = StateSerializer
    permission_classes = (permissions.AllowAny,)

class LGAViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = LGA.objects.all()
    serializer_class = LGASerializer
    permission_classes = (permissions.AllowAny,)

    def get_queryset(self):
        qs = super().get_queryset()
        state_id = self.request.query_params.get('state')
        if state_id:
            qs = qs.filter(state_id=state_id)
        return qs
