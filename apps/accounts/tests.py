from django.test import TestCase
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
