"""A student can be signed in on one device at a time. A newer sign-in replaces the older one."""
from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.sessions import device_label
from apps.exams.models import Exam, ExamSession
from apps.schools.models import School

PASSWORD = 'Strong-pass-123'


class DeviceLabelTest(SimpleTestCase):
    def test_names_the_browser_and_system(self):
        chrome_android = 'Mozilla/5.0 (Linux; Android 13; SM-A135F) AppleWebKit/537.36 Chrome/120.0 Mobile Safari/537.36'
        self.assertEqual(device_label(chrome_android), 'Chrome on Android')
        self.assertEqual(device_label('Mozilla/5.0 (Windows NT 10.0) Gecko/20100101 Firefox/121.0'), 'Firefox on Windows')
        self.assertEqual(device_label(''), 'Browser on unknown system')


class OneDeviceBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Queens', subdomain='queens-sess')
        self.student = User.objects.create_user(username='stu1', email='stu1@q.test', password=PASSWORD,
                                                role='student', school=self.school)
        self.teacher = User.objects.create_user(username='tea', email='tea@q.test', password=PASSWORD,
                                                role='teacher', school=self.school)
        self.admin = User.objects.create_user(username='adm', email='adm@q.test', password=PASSWORD,
                                              role='school_admin', school=self.school)

    def sign_in(self, device='phone', via='student-login/', username='stu1'):
        body = {'student_id': username, 'password': PASSWORD, 'device_id': device}
        if via == 'login/':
            body = {'email': username, 'password': PASSWORD, 'device_id': device}
        return APIClient().post('/api/auth/' + via, body, format='json')

    def api(self, tokens):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION='Bearer ' + tokens['access'])
        return c

    def start_exam(self):
        exam = Exam.objects.create(school=self.school, title='Maths', status='published', duration_mins=30)
        now = timezone.now()
        return ExamSession.objects.create(exam=exam, student=self.student, school=self.school, status='active',
                                          started_at=now, deadline=now + timedelta(minutes=30))


class OneDeviceTest(OneDeviceBase):

    def test_a_new_sign_in_replaces_the_old_one(self):
        first = self.sign_in('phone').json()
        self.assertEqual(self.api(first).get('/api/auth/me/').status_code, 200)
        second = self.sign_in('laptop').json()
        old = self.api(first).get('/api/auth/me/')
        self.assertEqual(old.status_code, 401)
        self.assertEqual(old.json()['code'], 'session_replaced')
        self.assertEqual(self.api(second).get('/api/auth/me/').status_code, 200)

    def test_the_replaced_device_cannot_refresh_its_way_back_in(self):
        first = self.sign_in('phone').json()
        self.sign_in('laptop')
        res = APIClient().post('/api/auth/refresh/', {'refresh': first['refresh']}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()['code'], 'session_replaced')

    def test_the_live_device_can_refresh(self):
        live = self.sign_in('phone').json()
        res = APIClient().post('/api/auth/refresh/', {'refresh': live['refresh']}, format='json')
        self.assertEqual(res.status_code, 200)
        # the new tokens still belong to the same live session
        self.assertEqual(self.api(res.json()).get('/api/auth/me/').status_code, 200)

    def test_signing_in_with_the_generated_email_is_held_to_one_device_too(self):
        first = self.sign_in('phone', via='login/', username='stu1@q.test').json()
        self.sign_in('laptop')
        self.assertEqual(self.api(first).get('/api/auth/me/').status_code, 401)

    def test_logging_out_ends_the_session_everywhere(self):
        tokens = self.sign_in('phone').json()
        self.assertEqual(self.api(tokens).post('/api/auth/logout/', {'refresh': tokens['refresh']}, format='json').status_code, 204)
        self.assertEqual(self.api(tokens).get('/api/auth/me/').status_code, 401)
        self.assertEqual(self.api(self.sign_in('phone').json()).get('/api/auth/me/').status_code, 200)

    def test_staff_can_use_several_devices(self):
        a = self.sign_in('d1', via='login/', username='tea@q.test').json()
        b = self.sign_in('d2', via='login/', username='tea@q.test').json()
        self.assertEqual(self.api(a).get('/api/auth/me/').status_code, 200)
        self.assertEqual(self.api(b).get('/api/auth/me/').status_code, 200)

    def test_a_school_can_turn_the_rule_off(self):
        self.school.single_device_students = False
        self.school.save()
        a = self.sign_in('phone').json()
        b = self.sign_in('laptop').json()
        self.assertEqual(self.api(a).get('/api/auth/me/').status_code, 200)
        self.assertEqual(self.api(b).get('/api/auth/me/').status_code, 200)

    def test_a_token_from_before_the_rule_keeps_working_until_the_next_sign_in(self):
        from rest_framework_simplejwt.tokens import AccessToken
        old = {'access': str(AccessToken.for_user(self.student))}            # no sid claim
        self.assertEqual(self.api(old).get('/api/auth/me/').status_code, 200)
        self.sign_in('phone')
        self.assertEqual(self.api(old).get('/api/auth/me/').status_code, 401)

    def test_the_sign_in_remembers_the_device_for_staff_to_see(self):
        APIClient().post('/api/auth/student-login/', {'student_id': 'stu1', 'password': PASSWORD, 'device_id': 'phone'},
                         format='json', HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 13) Chrome/120.0 Mobile Safari/537.36')
        self.student.refresh_from_db()
        self.assertEqual(self.student.session_device, 'Chrome on Android')
        self.assertIsNotNone(self.student.session_started_at)


class DuringAnExamTest(OneDeviceBase):

    def test_another_device_is_refused_while_an_exam_is_running(self):
        self.sign_in('phone')
        self.start_exam()
        res = self.sign_in('laptop')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()['code'], 'exam_in_progress_elsewhere')

    def test_the_same_device_can_sign_in_again_during_an_exam(self):
        self.sign_in('phone')
        self.start_exam()
        self.assertEqual(self.sign_in('phone').status_code, 200)

    def test_the_first_device_is_not_kicked_by_the_refused_attempt(self):
        first = self.sign_in('phone').json()
        self.start_exam()
        self.sign_in('laptop')
        self.assertEqual(self.api(first).get('/api/auth/me/').status_code, 200)

    def test_a_finished_exam_no_longer_blocks(self):
        self.sign_in('phone')
        session = self.start_exam()
        session.status = 'submitted'
        session.save()
        self.assertEqual(self.sign_in('laptop').status_code, 200)

    def test_an_exam_long_past_its_time_no_longer_blocks(self):
        self.sign_in('phone')
        session = self.start_exam()
        session.deadline = timezone.now() - timedelta(hours=2)
        session.save()
        self.assertEqual(self.sign_in('laptop').status_code, 200)


class SignOutEverywhereTest(OneDeviceBase):

    def url(self):
        return f'/api/students/{self.student.id}/sign_out_everywhere/'

    def as_user(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def test_a_teacher_can_release_a_student_stuck_on_a_dead_device_during_an_exam(self):
        old = self.sign_in('phone').json()
        self.start_exam()
        self.assertEqual(self.sign_in('laptop').status_code, 409)
        self.assertEqual(self.as_user(self.teacher).post(self.url()).status_code, 200)
        self.assertEqual(self.api(old).get('/api/auth/me/').status_code, 401)            # the old device is out
        self.assertEqual(self.sign_in('laptop').status_code, 200)                         # and the student gets in

    def test_an_admin_can_do_it(self):
        self.assertEqual(self.as_user(self.admin).post(self.url()).status_code, 200)

    def test_a_student_cannot_sign_out_another_student(self):
        other = User.objects.create_user(username='stu2', email='stu2@q.test', password=PASSWORD,
                                         role='student', school=self.school)
        self.assertEqual(self.as_user(other).post(self.url()).status_code, 403)

    def test_it_cannot_reach_a_student_of_another_school(self):
        other_school = School.objects.create(name='Other', subdomain='other-sess')
        outsider = User.objects.create_user(username='adm2', email='adm2@o.test', password=PASSWORD,
                                            role='school_admin', school=other_school)
        self.assertEqual(self.as_user(outsider).post(self.url()).status_code, 404)

    def test_the_student_detail_shows_where_they_are_signed_in(self):
        self.sign_in('phone')
        res = self.as_user(self.admin).get(f'/api/students/{self.student.id}/').json()
        self.assertEqual(res['signed_in_on'], 'Browser on unknown system')
        self.assertIsNotNone(res['signed_in_at'])
