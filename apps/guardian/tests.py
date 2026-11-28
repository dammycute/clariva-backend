from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import StudentAccessCode, User
from apps.base.encryption import hash_value
from apps.schools.models import School
from apps.students.models import StudentProfile


class AccessCodeTests(TestCase):
    def setUp(self):
        cache.clear()  # the lookup is rate limited
        self.school = School.objects.create(name='Queens College', subdomain='queens')
        student = User.objects.create_user(username='stu', school=self.school, role='student')
        StudentProfile.objects.create(user=student, school=self.school, admission_no='QC/2026/00001')
        StudentAccessCode.objects.create(student=student, code='CLR-ABCD1234')

    def lookup(self, **data):
        return APIClient().post('/api/portal/lookup/', {'subdomain': 'queens', **data}, format='json')

    def test_admission_number_with_code_works(self):
        res = self.lookup(admission_no='qc/2026/00001', code='clr-abcd1234')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data['admission_no'], 'QC/2026/00001')

    def test_code_alone_works(self):
        self.assertEqual(self.lookup(code='CLR-ABCD1234').status_code, 200)

    def test_never_says_which_half_was_wrong(self):
        wrong_code = self.lookup(admission_no='QC/2026/00001', code='CLR-WRONG000')
        wrong_number = self.lookup(admission_no='QC/2026/99999', code='CLR-ABCD1234')
        self.assertEqual((wrong_code.status_code, wrong_code.data), (wrong_number.status_code, wrong_number.data))
        self.assertEqual(wrong_code.status_code, 404)

    def test_code_is_not_readable_in_the_database(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT code, code_hash FROM %s' % StudentAccessCode._meta.db_table)
            stored, fingerprint = cursor.fetchone()
        self.assertNotIn(b'CLR-ABCD1234', bytes(stored))
        self.assertEqual(fingerprint, hash_value('CLR-ABCD1234'))
        self.assertEqual(StudentAccessCode.objects.get().code, 'CLR-ABCD1234')

    def test_fingerprint_depends_on_the_secret_key(self):
        before = hash_value('CLR-ABCD1234')
        with override_settings(LOOKUP_HASH_KEY='another-key'):
            self.assertNotEqual(hash_value('CLR-ABCD1234'), before)
