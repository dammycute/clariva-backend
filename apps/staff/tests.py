import uuid
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from apps.accounts.models import User
from apps.schools.models import School
from apps.students.models import StudentProfile
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


class StaffAuthorizationTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        self.school = School.objects.create(name='Test School', subdomain=f'test{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.student = _make_user('student', self.school)
        self.teacher_user = _make_user('teacher', self.school)
        self.parent = _make_user('parent', self.school)
        TeacherProfile.objects.create(user=self.teacher_user, school=self.school, status='active')

    def test_import_csv_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post('/api/staff/import_csv/', {'csv': 'first_name,last_name,email\nA,B,a@b.com'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_import_csv_parent_403(self):
        self.client.force_authenticate(self.parent)
        resp = self.client.post('/api/staff/import_csv/', {'csv': 'first_name,last_name,email\nA,B,a@b.com'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_import_csv_admin_200(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post('/api/staff/import_csv/', {'csv': 'first_name,last_name,email\nA,B,a@b.com'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_create_account_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post(f'/api/staff/{self.teacher_user.id}/create_account/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_account_parent_403(self):
        self.client.force_authenticate(self.parent)
        resp = self.client.post(f'/api/staff/{self.teacher_user.id}/create_account/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_account_admin_201(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f'/api/staff/{self.teacher_user.id}/create_account/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)


class StudentAuthorizationTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        self.school = School.objects.create(name='Test School', subdomain=f'test{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.principal = _make_user('principal', self.school)
        self.student = _make_user('student', self.school)
        self.parent = _make_user('parent', self.school)
        TeacherProfile.objects.create(user=self.principal, school=self.school, status='active')

    def test_promote_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post('/api/students/promote/', {'student_ids': [], 'target_class_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_promote_parent_403(self):
        self.client.force_authenticate(self.parent)
        resp = self.client.post('/api/students/promote/', {'student_ids': [], 'target_class_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_promote_principal_400(self):
        self.client.force_authenticate(self.principal)
        resp = self.client.post('/api/students/promote/', {'student_ids': [], 'target_class_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_bulk_create_accounts_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post('/api/students/bulk_create_accounts/', {'class_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_create_accounts_parent_403(self):
        self.client.force_authenticate(self.parent)
        resp = self.client.post('/api/students/bulk_create_accounts/', {'class_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_bulk_create_accounts_principal_200(self):
        self.client.force_authenticate(self.principal)
        resp = self.client.post('/api/students/bulk_create_accounts/', {'class_id': str(uuid.uuid4())}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_import_csv_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post('/api/students/import_csv/', {'csv': 'full_name\nA'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_import_csv_parent_403(self):
        self.client.force_authenticate(self.parent)
        resp = self.client.post('/api/students/import_csv/', {'csv': 'full_name\nA'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_import_csv_admin_200(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post('/api/students/import_csv/', {'csv': 'full_name\nA'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_reset_password_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post(f'/api/students/{self.student.id}/reset_password/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_reset_password_parent_403(self):
        self.client.force_authenticate(self.parent)
        resp = self.client.post(f'/api/students/{self.student.id}/reset_password/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_reset_password_admin_200(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f'/api/students/{self.student.id}/reset_password/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class ReportCardAuthorizationTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        from apps.exams.models import ReportCard
        self.school = School.objects.create(name='Test School', subdomain=f'test{uuid.uuid4().hex[:6]}')
        self.client = APIClient()
        self.admin = _make_user('school_admin', self.school)
        self.principal = _make_user('principal', self.school)
        self.teacher = _make_user('teacher', self.school)
        self.student = _make_user('student', self.school)
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

    def test_generate_principal_400(self):
        self.client.force_authenticate(self.principal)
        resp = self.client.post('/api/results/report-cards/generate/', {'class_id': str(uuid.uuid4()), 'term': 't', 'academic_year': 'y'}, format='json')
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TimetableAuthorizationTests(TestCase):
    def setUp(self):
        _thread_local.request = None
        from apps.exams.models import TimeTable
        from apps.classes.models import Class
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

    def test_unpublish_student_403(self):
        self.client.force_authenticate(self.student)
        resp = self.client.post(f'/api/timetable/timetables/{self.timetable.id}/unpublish/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN)

    def test_unpublish_admin_200(self):
        self.client.force_authenticate(self.admin)
        resp = self.client.post(f'/api/timetable/timetables/{self.timetable.id}/unpublish/', format='json')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
