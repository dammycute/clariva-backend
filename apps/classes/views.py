import re

from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.mixins import SchoolFilterMixin
from .models import Class
from .serializers import ClassSerializer

class ClassViewSet(SchoolFilterMixin, viewsets.ModelViewSet):
    queryset = Class.objects.select_related('form_teacher').all()
    serializer_class = ClassSerializer

    @action(detail=False, methods=['post'])
    def create_level(self, request):
        """Create a whole level at once: JSS1 with arms A, B and C makes JSS1A, JSS1B, JSS1C.

        Nobody should have to add JSS1A, then JSS1B, then JSS1C one at a time.
        """
        school = getattr(request.user, 'school', None)
        if school is None:
            return Response({'error': 'No school is assigned to your account.'},
                            status=status.HTTP_400_BAD_REQUEST)

        year_group = str(request.data.get('year_group') or '').strip().upper()
        if not year_group:
            return Response({'error': 'Choose a year group, such as JSS1.'},
                            status=status.HTTP_400_BAD_REQUEST)

        arms = self._arms_from(request.data.get('arms'))
        academic_year = str(request.data.get('academic_year') or '').strip() or None
        form_teacher = request.data.get('form_teacher') or None
        if form_teacher and not User.objects.filter(pk=form_teacher, school=school).exists():
            form_teacher = None

        created, skipped = [], []
        with transaction.atomic():
            for arm in arms:
                name = f'{year_group}{arm}'
                if Class.objects.filter(
                        school=school, name=name, academic_year=academic_year).exists():
                    skipped.append(name)
                    continue
                row = Class.objects.create(
                    school=school, name=name, year_group=year_group,
                    arm=arm or None, academic_year=academic_year,
                    form_teacher_id=form_teacher,
                )
                created.append({'id': str(row.pk), 'name': row.name, 'arm': row.arm})

        return Response(
            {'created': created, 'skipped': skipped, 'count': len(created)},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @staticmethod
    def _arms_from(raw):
        """['A', 'B'] out of a list, 'A,B', a span 'A-C', or a count such as '3'."""
        if raw in (None, '', []):
            return ['']
        if isinstance(raw, (list, tuple)):
            arms = [str(a).strip().upper() for a in raw if str(a).strip()]
        else:
            text = str(raw).strip().upper()
            span = re.match(r'^([A-Z])\s*[-\u2013]\s*([A-Z])$', text)
            if span and span.group(1) <= span.group(2):
                arms = [chr(c) for c in range(ord(span.group(1)), ord(span.group(2)) + 1)]
            elif text.isdigit():
                arms = [chr(ord('A') + i) for i in range(int(text))]
            else:
                arms = [a for a in re.split(r'[\s,;]+', text) if a]
        cleaned = [re.sub(r'[^A-Z0-9]', '', a)[:2] for a in arms]
        return [a for a in cleaned if a][:12] or ['']

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        teacher_id = self.request.query_params.get('teacher_id')

        if teacher_id == 'me' and user.role == 'teacher':
            qs = qs.filter(form_teacher=user)
        elif teacher_id:
            qs = qs.filter(form_teacher_id=teacher_id)
        return qs
