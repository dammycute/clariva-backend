import uuid
from decimal import Decimal
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User
from apps.schools.models import School, GradingConfig
from apps.audit.models import ActivityLog
from apps.audit.signals import _thread_local
from apps.staff.permissions import IsSchoolAdminRole

ADMIN_ROLES = ('super_admin', 'school_admin', 'principal', 'admin_officer')


def _make_user(role, school=None, **kwargs):
    return User.objects.create_user(
        username=f'{role}_{uuid.uuid4().hex[:8]}',
        email=f'{role}_{uuid.uuid4().hex[:8]}@test.com',
        password='testpass123',
        role=role,
        school=school,
        **kwargs,
    )


class SchoolViewSetTenantScopingTests(TestCase):
    """Verify SchoolViewSet.get_queryset scopes by user.school."""

    def setUp(self):
        _thread_local.request = None
        self.school_a = School.objects.create(name='School A', subdomain=f'a-{uuid.uuid4().hex[:6]}')
        self.school_b = School.objects.create(name='School B', subdomain=f'b-{uuid.uuid4().hex[:6]}')
        self.client = APIClient()

    def test_school_admin_lists_only_own_school(self):
        user = _make_user('school_admin', self.school_a)
        self.client.force_authenticate(user)
        resp = self.client.get('/api/schools/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [s['id'] for s in resp.data.get('results', resp.data)]
        self.assertEqual(ids, [str(self.school_a.id)])

    def test_teacher_lists_only_own_school(self):
        user = _make_user('teacher', self.school_b)
        self.client.force_authenticate(user)
        resp = self.client.get('/api/schools/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [s['id'] for s in resp.data.get('results', resp.data)]
        self.assertEqual(ids, [str(self.school_b.id)])

    def test_super_admin_with_school_lists_only_own(self):
        user = _make_user('super_admin', self.school_a)
        self.client.force_authenticate(user)
        resp = self.client.get('/api/schools/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [s['id'] for s in resp.data.get('results', resp.data)]
        self.assertEqual(ids, [str(self.school_a.id)])

    def test_super_admin_without_school_lists_all(self):
        user = _make_user('super_admin', school=None)
        self.client.force_authenticate(user)
        resp = self.client.get('/api/schools/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [s['id'] for s in resp.data.get('results', resp.data)]
        self.assertCountEqual(ids, [str(self.school_a.id), str(self.school_b.id)])

    def test_user_without_school_gets_permission_denied(self):
        user = _make_user('teacher', school=None)
        self.client.force_authenticate(user)
        resp = self.client.get('/api/schools/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_suspended_school_raises_permission_denied(self):
        self.school_a.status = 'suspended'
        self.school_a.save()
        user = _make_user('school_admin', self.school_a)
        self.client.force_authenticate(user)
        resp = self.client.get('/api/schools/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)


class BackupAuthorizationTests(TestCase):
    """Verify backup endpoint: IsSchoolAdminRole gate, super_admin school_id support."""

    def setUp(self):
        _thread_local.request = None
        self.school = School.objects.create(name='Test School', subdomain=f't-{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.teacher = _make_user('teacher', self.school)
        self.super_no_school = _make_user('super_admin', school=None)
        self.super_with_school = _make_user('super_admin', self.school)

    def test_student_403(self):
        student = _make_user('student', self.school)
        self.client.force_authenticate(student)
        resp = self.client.get('/api/schools/backup/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_teacher_403(self):
        self.client.force_authenticate(self.teacher)
        resp = self.client.get('/api/schools/backup/')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_school_admin_200(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.get('/api/schools/backup/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        data = resp.json()
        self.assertEqual(data['school_id'], str(self.school.id))
        self.assertIn('data', data)
        self.assertIn('counts', data)

    def test_super_admin_with_school_200(self):
        self.client.force_authenticate(self.super_with_school)
        resp = self.client.get('/api/schools/backup/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()['school_id'], str(self.school.id))

    def test_super_admin_no_school_requires_school_id(self):
        self.client.force_authenticate(self.super_no_school)
        resp = self.client.get('/api/schools/backup/')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_super_admin_no_school_with_param_200(self):
        self.client.force_authenticate(self.super_no_school)
        resp = self.client.get(f'/api/schools/backup/?school_id={self.school.id}')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()['school_id'], str(self.school.id))

    def test_super_admin_no_school_bad_school_id_404(self):
        self.client.force_authenticate(self.super_no_school)
        resp = self.client.get('/api/schools/backup/?school_id=00000000-0000-0000-0000-000000000000')
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_backup_creates_activity_log(self):
        self.client.force_authenticate(self.admin)
        self.client.get('/api/schools/backup/')
        log = ActivityLog.objects.filter(
            school=self.school, user=self.admin, action='exported'
        ).first()
        self.assertIsNotNone(log)


class GradingAuthorizationTests(TestCase):
    """Verify grading endpoint: GET readable by any auth; PUT/PATCH gated to IsSchoolAdminRole."""

    def setUp(self):
        _thread_local.request = None
        self.school = School.objects.create(name='Test School', subdomain=f'g-{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.teacher = _make_user('teacher', self.school)
        self.super_no_school = _make_user('super_admin', school=None)

    def test_grading_get_authed_200(self):
        self.client.force_authenticate(self.teacher)
        resp = self.client.get(f'/api/schools/{self.school.id}/grading/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('components', resp.json())

    def test_grading_put_teacher_403(self):
        self.client.force_authenticate(self.teacher)
        resp = self.client.put(
            f'/api/schools/{self.school.id}/grading/',
            {'components': [], 'grade_boundaries': []},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_grading_put_admin_200(self):
        self.client.force_authenticate(self.admin)
        payload = {
            'components': [{'key': 'exam', 'label': 'Exam', 'max': 100, 'enabled': True}],
            'grade_boundaries': [{'name': 'A', 'min_pct': 70}],
        }
        resp = self.client.put(f'/api/schools/{self.school.id}/grading/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_grading_patch_admin_200(self):
        GradingConfig.objects.get_or_create(
            school=self.school,
            defaults={'components': [{'key': 'exam', 'max': 100, 'enabled': True}],
                      'grade_boundaries': [{'name': 'A', 'min_pct': 70}]},
        )
        self.client.force_authenticate(self.admin)
        resp = self.client.patch(
            f'/api/schools/{self.school.id}/grading/',
            {'grade_boundaries': [{'name': 'B', 'min_pct': 60}]},
            format='json',
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_grading_get_creates_default_config(self):
        self.client.force_authenticate(self.admin)
        self.client.get(f'/api/schools/{self.school.id}/grading/')
        gc = GradingConfig.objects.get(school=self.school)
        self.assertEqual(len(gc.components), 4)
        self.assertEqual(len(gc.grade_boundaries), 9)


class RestoreAuthorizationTests(TestCase):
    """Verify restore endpoint: role gates, confirm flag, data validation."""

    def setUp(self):
        _thread_local.request = None
        self.school = School.objects.create(name='Test School', subdomain=f'r-{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.teacher = _make_user('teacher', self.school)
        self.super = _make_user('super_admin', self.school)

    def test_teacher_403(self):
        self.client.force_authenticate(self.teacher)
        resp = self.client.post('/api/schools/restore/', {'confirm': True}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_admin_missing_confirm_400(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post('/api/schools/restore/', {'data': []}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('confirm', resp.json()['error'].lower())

    def test_admin_invalid_model_rejected(self):
        self.client.force_authenticate(self.admin)
        payload = {'confirm': True, 'data': [{'model': 'evil.Model', 'fields': {}}]}
        resp = self.client.post('/api/schools/restore/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_wrong_school_rejected(self):
        other = School.objects.create(name='Other', subdomain=f'o-{uuid.uuid4().hex[:6]}')
        self.client.force_authenticate(self.admin)
        payload = {'confirm': True, 'data': [{'model': 'classes.Class', 'fields': {'school': str(other.id)}}]}
        resp = self.client.post('/api/schools/restore/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_super_admin_no_school_needs_payload_school_id(self):
        super_no_school = _make_user('super_admin', school=None)
        self.client.force_authenticate(super_no_school)
        payload = {'confirm': True, 'data': []}
        resp = self.client.post('/api/schools/restore/', payload, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
