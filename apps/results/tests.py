import uuid
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User
from apps.schools.models import School, GradingConfig
from apps.exams.models import ReportCard, Subject
from apps.staff.models import TeacherProfile
from apps.audit.signals import _thread_local


def _make_user(role, school=None, **kwargs):
    return User.objects.create_user(
        username=f'{role}_{uuid.uuid4().hex[:8]}',
        email=f'{role}_{uuid.uuid4().hex[:8]}@test.com',
        password='testpass123',
        role=role,
        school=school,
        **kwargs,
    )


class ReportCardAuthorizationTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        self.school = School.objects.create(name='Test School', subdomain=f'test{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.principal = _make_user('principal', self.school)
        self.teacher = _make_user('teacher', self.school)
        self.student = _make_user('student', self.school)
        self.parent = _make_user('parent', self.school)
        TeacherProfile.objects.create(user=self.principal, school=self.school, status='active')
        TeacherProfile.objects.create(user=self.teacher, school=self.school, status='active')
        self.card = ReportCard.objects.create(
            school=self.school, student=self.student,
            term='First Term', academic_year='2025/2026',
            grades=[], total_score=0, total_possible=1, average=0,
        )
        self.base = f'/api/results/report-cards/{self.card.id}'

    def test_release_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post(f'{self.base}/release/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_release_teacher_403(self):
        self.client.force_authenticate(self.teacher)
        resp = self.client.post(f'{self.base}/release/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_release_principal_200(self):
        self.client.force_authenticate(self.principal)
        resp = self.client.post(f'{self.base}/release/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_unrelease_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post(f'{self.base}/unrelease/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unrelease_teacher_403(self):
        self.client.force_authenticate(self.teacher)
        resp = self.client.post(f'{self.base}/unrelease/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unrelease_principal_200(self):
        self.client.force_authenticate(self.principal)
        resp = self.client.post(f'{self.base}/unrelease/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_generate_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post('/api/results/report-cards/generate/', {'class_id': str(uuid.uuid4()), 'term': 't', 'academic_year': 'y'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_generate_teacher_403(self):
        self.client.force_authenticate(self.teacher)
        resp = self.client.post('/api/results/report-cards/generate/', {'class_id': str(uuid.uuid4()), 'term': 't', 'academic_year': 'y'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_generate_principal_400_missing_fields(self):
        self.client.force_authenticate(self.principal)
        resp = self.client.post('/api/results/report-cards/generate/', {}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_principal_400_no_students(self):
        self.client.force_authenticate(self.principal)
        from apps.classes.models import Class
        cls = Class.objects.create(school=self.school, name='Empty', year_group='JSS1')
        resp = self.client.post('/api/results/report-cards/generate/', {
            'class_id': str(cls.id), 'term': 't', 'academic_year': 'y'
        }, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class ReportCardTenantScopingTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        self.school_a = School.objects.create(name='School A', subdomain=f'a-{uuid.uuid4().hex[:6]}')
        self.school_b = School.objects.create(name='School B', subdomain=f'b-{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin_a = _make_user('school_admin', self.school_a)
        self.admin_b = _make_user('school_admin', self.school_b)
        self.student_a = _make_user('student', self.school_a)
        self.card_a = ReportCard.objects.create(
            school=self.school_a, student=self.student_a,
            term='First Term', academic_year='2025/2026',
            grades=[], total_score=0, total_possible=1, average=0,
        )

    def test_school_admin_sees_only_own_cards(self):
        self.client.force_authenticate(self.admin_a)
        resp = self.client.get('/api/results/report-cards/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [c['id'] for c in resp.data.get('results', resp.data)]
        self.assertEqual(ids, [str(self.card_a.id)])

    def test_other_school_cannot_see_cards(self):
        self.client.force_authenticate(self.admin_b)
        resp = self.client.get('/api/results/report-cards/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [c['id'] for c in resp.data.get('results', resp.data)]
        self.assertEqual(ids, [])
