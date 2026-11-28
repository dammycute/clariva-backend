import json
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User


class PrivilegeEscalationTests(TestCase):
    def setUp(self):
        from apps.schools.models import School
        from rest_framework.test import APIClient
        self.school = School.objects.create(name='S', subdomain='s-esc')
        self.user = User.objects.create_user(
            username='stu', email='stu@example.com', password='x-Strong-pass-1',
            role='student', school=self.school,
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_me_patch_cannot_change_role_or_school(self):
        resp = self.client.patch('/api/auth/me/', {'role': 'super_admin', 'first_name': 'New'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.role, 'student')
        self.assertEqual(self.user.first_name, 'New')

    def test_student_cannot_write_attendance_or_classes(self):
        self.assertEqual(self.client.post('/api/attendance/', {}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/classes/', {}, format='json').status_code, 403)

    def test_student_cannot_read_audit_log(self):
        self.assertEqual(self.client.get('/api/audit/').status_code, 403)


MAIL = dict(RESEND_API_KEY='re_test',
            DEMO_FROM_EMAIL='Clarriva <onboarding@resend.dev>')


class GeneratedAdminEmailTests(TestCase):
    """A generated admin login reaches the new admin by email, and is still returned."""

    def setUp(self):
        self.owner = User.objects.create_user(
            username='owner', email='owner@example.com', password='owner-pass-1', role='super_admin',
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.owner)

    def post(self, email='new@example.com'):
        return self.client.post('/api/auth/admin/generate-login/', {'email': email}, format='json')

    @override_settings(**MAIL)
    def test_the_new_admin_is_emailed_their_login(self):
        with mock.patch('apps.base.mail.urlopen') as sent:
            res = self.post()
        self.assertEqual(res.status_code, 201)
        body = json.loads(sent.call_args[0][0].data)
        self.assertEqual(body['to'], ['new@example.com'])
        self.assertEqual(body['subject'], 'Your Clarriva admin login')
        self.assertIn(res.json()['password'], body['text'])
        self.assertIn('new@example.com', body['text'])
        self.assertIn('/login', body['text'])
        self.assertTrue(res.json()['emailed'])

    @override_settings(RESEND_API_KEY='')
    def test_the_login_still_works_when_email_is_not_set_up(self):
        with mock.patch('apps.base.mail.urlopen') as sent:
            res = self.post()
        self.assertEqual(res.status_code, 201)
        sent.assert_not_called()
        self.assertFalse(res.json()['emailed'])
        self.assertTrue(res.json()['password'])

    @override_settings(**MAIL)
    def test_a_failed_email_does_not_lose_the_new_admin(self):
        with mock.patch('apps.base.mail.urlopen', side_effect=OSError('down')):
            res = self.post()
        self.assertEqual(res.status_code, 201)
        self.assertFalse(res.json()['emailed'])
        self.assertTrue(User.objects.filter(email='new@example.com').exists())
