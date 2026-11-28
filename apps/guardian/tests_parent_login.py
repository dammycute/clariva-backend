from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.classes.models import Class
from apps.schools.models import School


class ParentLoginTests(TestCase):
    def setUp(self):
        cache.clear()  # sign-in is rate limited
        self.school = School.objects.create(name='Queens College', subdomain='queens')
        self.admin = User.objects.create_user(username='admin', school=self.school, role='school_admin')
        self.cls = Class.objects.create(school=self.school, name='JSS 1A')
        self.api = APIClient()
        self.api.force_authenticate(self.admin)

    def import_one(self):
        res = self.api.post('/api/students/import_csv/',
                            {'csv': 'full_name\nAda Obi', 'class_id': str(self.cls.id)}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        return res.data['students'][0]

    def sign_in(self, login, password):
        client = APIClient()
        res = client.post('/api/auth/login/', {'email': login, 'password': password}, format='json')
        if res.status_code == 200:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {res.data['access']}")
        return res, client

    def test_a_new_student_comes_with_a_parent_login(self):
        row = self.import_one()
        self.assertNotEqual(row['password'], row['parent_password'])
        res, client = self.sign_in(row['admission_no'].lower(), row['parent_password'])
        self.assertEqual((res.status_code, res.data['role']), (200, 'parent'), res.content)
        children = client.get('/api/portal/children/')
        self.assertEqual([c['admission_no'] for c in children.data], [row['admission_no']])

    def test_the_student_password_does_not_open_the_parent_account(self):
        row = self.import_one()
        res, _ = self.sign_in(row['admission_no'], row['password'])
        self.assertEqual(res.status_code, 401)

    def test_nobody_is_forced_to_change_a_password(self):
        row = self.import_one()
        self.assertFalse(User.objects.filter(role__in=('student', 'parent'), must_change_password=True).exists())
        res, _ = self.sign_in(row['admission_no'], row['parent_password'])
        self.assertFalse(res.data['must_change_password'])

    def test_a_parent_cannot_read_school_records(self):
        row = self.import_one()
        _, client = self.sign_in(row['admission_no'], row['parent_password'])
        for path in ('/api/students/', '/api/staff/', '/api/classes/', '/api/grades/', '/api/attendance/',
                     '/api/fees/invoices/', '/api/schools/', '/api/billing/status/',
                     '/api/comms/announcements/', '/api/timetable/', '/api/exams/subjects/'):
            self.assertEqual(client.get(path).status_code, 403, path)
        self.assertEqual(client.get('/api/auth/me/').status_code, 200)

    def test_bulk_fills_only_what_is_missing(self):
        self.import_one()
        again = self.api.post('/api/students/bulk_create_accounts/', {'class_id': str(self.cls.id)}, format='json')
        self.assertEqual(again.data['created'], [])
        User.objects.filter(role='parent').delete()          # a student from before parent logins
        res = self.api.post('/api/students/bulk_create_accounts/', {'class_id': str(self.cls.id)}, format='json')
        [row] = res.data['created']
        self.assertEqual(row['password'], '')                # the student's password is left alone
        self.assertTrue(row['parent_password'])

    def test_reset_replaces_the_parent_password_without_a_second_account(self):
        row = self.import_one()
        student = User.objects.get(role='student')
        res = self.api.post(f'/api/students/{student.id}/reset_parent_password/')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(User.objects.filter(role='parent').count(), 1)
        self.assertEqual(self.sign_in(row['admission_no'], row['parent_password'])[0].status_code, 401)
        self.assertEqual(self.sign_in(row['admission_no'], res.data['parent_password'])[0].status_code, 200)
