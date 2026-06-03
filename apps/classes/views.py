from rest_framework import viewsets
from apps.mixins import SchoolFilterMixin
from .models import Class
from .serializers import ClassSerializer

class ClassViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Class.objects.all()
    serializer_class = ClassSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        teacher_id = self.request.query_params.get('teacher_id')

        if teacher_id == 'me' and user.role == 'teacher':
            staff = user.staff_set.first()
            if staff:
                qs = qs.filter(form_teacher=staff)
        elif teacher_id:
            qs = qs.filter(form_teacher_id=teacher_id)
        return qs
