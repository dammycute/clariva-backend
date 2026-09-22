import uuid
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User
from apps.schools.models import School
from apps.exams.models import TimeTable
from apps.classes.models import Class
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


class TimetableAuthorizationTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        self.school = School.objects.create(name='Test School', subdomain=f'test{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.student = _make_user('student', self.school)
        TeacherProfile.objects.create(user=self.admin, school=self.school, status='active')
        self.class_group = Class.objects.create(school=self.school, name='JSS 1A', year_group='JSS1', arm='A')
        self.timetable = TimeTable.objects.create(
            school=self.school, class_group=self.class_group,
            term='First Term', academic_year='2025/2026',
        )

    def test_publish_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post(f'/api/timetable/timetables/{self.timetable.id}/publish/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_publish_admin_200(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f'/api/timetable/timetables/{self.timetable.id}/publish/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.timetable.refresh_from_db()
        self.assertTrue(self.timetable.is_published)

    def test_unpublish_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post(f'/api/timetable/timetables/{self.timetable.id}/unpublish/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unpublish_admin_200(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f'/api/timetable/timetables/{self.timetable.id}/unpublish/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.timetable.refresh_from_db()
        self.assertFalse(self.timetable.is_published)


class TimetableTenantScopingTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        self.school_a = School.objects.create(name='School A', subdomain=f'a-{uuid.uuid4().hex[:6]}')
        self.school_b = School.objects.create(name='School B', subdomain=f'b-{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin_a = _make_user('school_admin', self.school_a)
        self.admin_b = _make_user('school_admin', self.school_b)
        cls_a = Class.objects.create(school=self.school_a, name='JSS 1', year_group='JSS1')
        cls_b = Class.objects.create(school=self.school_b, name='JSS 1', year_group='JSS1')
        self.tt_a = TimeTable.objects.create(
            school=self.school_a, class_group=cls_a,
            term='First Term', academic_year='2025/2026',
        )
        self.tt_b = TimeTable.objects.create(
            school=self.school_b, class_group=cls_b,
            term='First Term', academic_year='2025/2026',
        )

    def test_school_admin_sees_only_own_timetables(self):
        self.client.force_authenticate(self.admin_a)
        resp = self.client.get('/api/timetable/timetables/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [t['id'] for t in resp.data.get('results', resp.data)]
        self.assertEqual(ids, [str(self.tt_a.id)])

    def test_other_school_cannot_see_timetables(self):
        self.client.force_authenticate(self.admin_b)
        resp = self.client.get('/api/timetable/timetables/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        ids = [t['id'] for t in resp.data.get('results', resp.data)]
        self.assertNotIn(str(self.tt_a.id), ids)
