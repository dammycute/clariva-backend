"""Student accounts: generated logins, the detail page's data, and adding a student."""
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.classes.models import Class
from apps.schools.models import School
from apps.students.models import StudentProfile
from apps.students.serializers import school_code


class StudentAccountsTest(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Queens', subdomain='queens-stu')
        self.cls = Class.objects.create(school=self.school, name='JSS1A', year_group='JSS1', arm='A')
        self.admin = User.objects.create_user(username='adm', email='adm@t.com', password='pass1234',
                                              school=self.school, role='school_admin')
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)
        # A student as the CSV import makes it: no password yet.
        self.stu = User.objects.create(school=self.school, username='student.1', first_name='Ada',
                                       last_name='Obi', role='student')
        StudentProfile.objects.create(school=self.school, user=self.stu, admission_no='CLR/2026/00001',
                                      class_group=self.cls, student_status='active')

    def _generate(self):
        res = self.api.post('/api/students/bulk_create_accounts/', {'class_id': str(self.cls.id)}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        return res.json()['created'][0]

    def test_generated_account_has_an_admission_number_login_that_works(self):
        row = self._generate()
        self.assertEqual(row['admission_no'], 'CLR/2026/00001')
        anon = APIClient()
        res = anon.post('/api/auth/student-login/',
                        {'student_id': row['admission_no'], 'password': row['password']}, format='json')
        self.assertEqual(res.status_code, 200, res.content)

    def test_login_still_works_when_the_school_is_sent(self):
        row = self._generate()
        res = APIClient().post('/api/auth/student-login/', {
            'student_id': row['admission_no'], 'password': row['password'], 'school_id': str(self.school.id)},
            format='json')
        self.assertEqual(res.status_code, 200, res.content)

    def test_wrong_password_gives_the_generic_error(self):
        self._generate()
        res = APIClient().post('/api/auth/student-login/',
                               {'student_id': 'CLR/2026/00001', 'password': 'nope'}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_detail_returns_profile_and_account_info(self):
        self._generate()
        res = self.api.get(f'/api/students/{self.stu.id}/')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body['admission_no'], 'CLR/2026/00001')
        self.assertTrue(body['has_account'])

    def test_detail_side_lists_work(self):
        self.assertEqual(self.api.get('/api/fees/invoices/', {'student_id': str(self.stu.id)}).status_code, 200)
        self.assertEqual(self.api.get('/api/attendance/', {'student_id': str(self.stu.id)}).status_code, 200)

    def test_add_student_needs_no_username_and_keeps_the_profile(self):
        res = self.api.post('/api/students/', {
            'first_name': 'Bayo', 'last_name': 'Ade', 'gender': 'Male', 'class_group': str(self.cls.id),
            'guardian_name': 'Mr Ade', 'guardian_phone': '08011111111'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        user = User.objects.get(pk=res.json()['id'])
        self.assertEqual(user.school, self.school)
        self.assertEqual(user.student_profile.class_group, self.cls)
        self.assertEqual(user.student_profile.guardian_name, 'Mr Ade')
        self.assertTrue(user.student_profile.admission_no)

    def test_add_student_with_an_admission_number(self):
        res = self.api.post('/api/students/', {
            'first_name': 'Chi', 'last_name': 'Eze', 'admission_no': 'CLR/2026/99999'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(res.json()['admission_no'], 'CLR/2026/99999')

    def test_a_student_added_by_hand_gets_an_account_from_the_class_button(self):
        res = self.api.post('/api/students/', {
            'first_name': 'Dayo', 'last_name': 'Bello', 'class_group': str(self.cls.id)}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertFalse(res.json()['has_account'])
        made = self.api.post('/api/students/bulk_create_accounts/', {'class_id': str(self.cls.id)}, format='json')
        self.assertEqual(len(made.json()['created']), 2)           # Ada (imported) and Dayo (added by hand)

    def test_the_generated_email_also_works_as_a_login(self):
        row = self._generate()
        res = APIClient().post('/api/auth/student-login/',
                               {'student_id': row['email'], 'password': row['password']}, format='json')
        self.assertEqual(res.status_code, 200, res.content)

    def test_import_ignores_admission_no_and_generates_it(self):
        csv_text = ('full_name,admission_no,gender,class\n'
                    'Femi Ola,SHOULD-BE-IGNORED,Male,JSS1A\n'
                    'Ngozi Eze,,Female,JSS1A\n'
                    'Bad Row,,Male,NOCLASS\n')
        res = self.api.post('/api/students/import_csv/', {'csv': csv_text}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body['created'], 2)
        self.assertEqual(len(body['errors']), 1)
        numbers = [s['admission_no'] for s in body['students']]
        self.assertEqual(len(set(numbers)), 2)
        code = school_code(self.school)
        self.assertTrue(all(n.startswith(f'{code}/') for n in numbers))
        self.assertFalse(StudentProfile.objects.filter(admission_no='SHOULD-BE-IGNORED').exists())
        self.assertEqual(StudentProfile.objects.filter(class_group=self.cls).count(), 3)   # Ada + 2 imported

    def test_import_after_a_delete_does_not_clash(self):
        self.api.post('/api/students/import_csv/', {'csv': 'full_name\nOne Two\nThree Four\n'}, format='json')
        User.objects.filter(first_name='One').delete()
        res = self.api.post('/api/students/import_csv/', {'csv': 'full_name\nFive Six\n'}, format='json')
        self.assertEqual(res.json()['created'], 1, res.content)
        self.assertEqual(res.json()['errors'], [])

class TeacherRosterTest(TestCase):
    """A form teacher adds and imports students into their own class only."""

    def setUp(self):
        self.school = School.objects.create(name='Queens T', subdomain='queens-teach')
        self.mine = Class.objects.create(school=self.school, name='JSS1A', year_group='JSS1', arm='A')
        self.other = Class.objects.create(school=self.school, name='JSS1B', year_group='JSS1', arm='B')
        self.teacher = User.objects.create_user(username='t1', email='t1@t.com', password='pass1234',
                                                school=self.school, role='teacher')
        self.mine.form_teacher = self.teacher
        self.mine.save()
        self.api = APIClient()
        self.api.force_authenticate(user=self.teacher)

    def test_a_form_teacher_adds_a_student_to_their_own_class(self):
        res = self.api.post('/api/students/', {'first_name': 'Ada', 'last_name': 'Obi',
                                               'class_group': str(self.mine.id)}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(StudentProfile.objects.get(user_id=res.json()['id']).class_group, self.mine)

    def test_a_form_teacher_cannot_add_to_another_class(self):
        res = self.api.post('/api/students/', {'first_name': 'Ada', 'last_name': 'Obi',
                                               'class_group': str(self.other.id)}, format='json')
        self.assertEqual(res.status_code, 403, res.content)

    def test_a_form_teacher_imports_into_their_own_class(self):
        res = self.api.post('/api/students/import_csv/',
                            {'csv': 'full_name,gender\nAda Obi,Female\n', 'class_id': str(self.mine.id)},
                            format='json')
        self.assertEqual(res.status_code, 200, res.content)
        body = res.json()
        self.assertEqual(body['created'], 1)
        self.assertTrue(body['students'][0]['password'])
        self.assertEqual(StudentProfile.objects.filter(class_group=self.mine).count(), 1)

    def test_a_form_teacher_cannot_import_into_another_class(self):
        res = self.api.post('/api/students/import_csv/',
                            {'csv': 'full_name\nAda Obi\n', 'class_id': str(self.other.id)},
                            format='json')
        self.assertEqual(res.status_code, 403, res.content)
        self.assertEqual(StudentProfile.objects.count(), 0)


class SchoolCodeTests(SimpleTestCase):
    def test_admission_numbers_start_with_a_short_school_code(self):
        for name, code in (('Queens College', 'QC'), ('Government Secondary School', 'GSS'),
                           ("St. Mary's College of Education", 'SMCE'), ('Greenfield', 'GRE'),
                           ('The Light of Hope and Joy International Model Academy', 'LHJIM'), ('', 'SCH')):
            self.assertEqual(school_code(School(name=name)), code, name)
