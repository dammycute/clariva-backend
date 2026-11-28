from rest_framework.test import APITestCase

from apps.accounts.models import User
from apps.schools.models import School


class WalkthroughTests(APITestCase):
    def setUp(self):
        school = School.objects.create(name='Queens College', subdomain='queens')
        self.user = User.objects.create_user(username='t', email='t@x.com', password='pw-123456-ok',
                                             role='teacher', school=school)
        self.client.force_authenticate(self.user)

    def test_new_account_can_finish_the_guide_and_nothing_else_changes(self):
        self.assertFalse(self.client.get('/api/auth/me/').json()['walkthrough_done'])
        res = self.client.patch('/api/auth/me/', {'walkthrough_done': True, 'role': 'super_admin'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.walkthrough_done)
        self.assertEqual(self.user.role, 'teacher')
