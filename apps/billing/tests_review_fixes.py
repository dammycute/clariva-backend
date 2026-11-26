"""Regression tests for the problems found in review: money, access and who may do what."""
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.exams.models import Exam, ExamSession
from apps.locations.models import State
from apps.schools.models import School
from . import services
from .exceptions import StudentLimitReached
from .models import Payment, TermCalendar
from .views import safe_callback

PASSWORD = 'Strong-pass-123'


def paid(payment):
    return {'status': 'success', 'currency': 'NGN', 'amount': payment.amount, 'reference': payment.reference}


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.today = timezone.localdate()
        state, _ = State.objects.get_or_create(name='Lagos', defaults={'code': 'LA'})
        self.school = School.objects.create(name='P', subdomain='p-school', state='Lagos', status='pending',
                                            current_term='1st Term', current_academic_year='2026/2027',
                                            declared_students=40)
        self.admin = User.objects.create_user(username='a', email='a@p.test', password=PASSWORD,
                                              role='school_admin', school=self.school)
        for year, term, days in [('2026/2027', '1st Term', -30), ('2026/2027', '2nd Term', 40),
                                 ('2026/2027', '3rd Term', 170), ('2027/2028', '1st Term', 300)]:
            TermCalendar.objects.create(state=state, academic_year=year, term=term,
                                        resumes_on=self.today + timedelta(days=days))
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)

    def start(self, **body):
        with patch('apps.billing.paystack.initialize', return_value={'authorization_url': 'https://x'}):
            res = self.api.post('/api/billing/payments/initialize/', body, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        return Payment.objects.get(reference=res.json()['reference'])

    def settle(self, payment):
        result = services.fulfil_payment(payment, paid(payment))
        self.school.refresh_from_db()
        self.admin.refresh_from_db()
        return result


class MoneyTest(Base):
    def test_an_upgrade_does_not_skip_a_term(self):
        self.settle(self.start())
        upgrade = self.start(kind='upgrade', students=100)
        self.assertEqual(upgrade.term, '1st Term')                       # places for the current term
        self.settle(upgrade)
        self.assertEqual(self.school.paid_blocks, 2)
        self.assertEqual(services.term_to_pay(self.school), ('2026/2027', '2nd Term'))

    def test_an_old_payment_finished_late_takes_nothing_away(self):
        self.settle(self.start())
        stale = self.start(kind='upgrade', students=100)
        newer = Payment.objects.create(
            school=self.school, reference='CLV-newer', kind='renewal', amount=9000000, blocks_after=3,
            academic_year='2026/2027', term='2nd Term', covers_from=self.today,
            access_until=self.school.access_until + timedelta(days=100))
        self.settle(newer)
        result = self.settle(stale)
        self.assertEqual((self.school.access_until, self.school.paid_blocks), (newer.access_until, 3))
        self.assertEqual(result.status, 'paid')                          # the money is on record
        self.assertTrue(result.note.startswith(services.REVIEW))

    def test_a_second_payment_for_one_term_is_held_for_review(self):
        first, second = self.start(), self.start()
        self.settle(first)
        result = self.settle(second)
        self.assertIn('already paid', result.note)
        self.assertEqual(services.term_to_pay(self.school), ('2026/2027', '2nd Term'))

    @override_settings(BILLING_ENFORCE=True)
    def test_a_date_only_grant_still_limits_students(self):
        root = User.objects.create_user(username='root', email='r@p.test', password=PASSWORD, role='super_admin')
        api = APIClient()
        api.force_authenticate(user=root)
        res = api.post('/api/billing/admin/payments/manual/',
                       {'school': str(self.school.pk), 'access_until': str(self.today + timedelta(days=30))},
                       format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.school.refresh_from_db()
        self.assertEqual(self.school.paid_blocks, 1)                     # from the declared 40
        with self.assertRaises(StudentLimitReached):
            services.check_capacity(self.school, 61)
        self.assertEqual(services.term_to_pay(self.school), ('2026/2027', '1st Term'))
        self.assertEqual(api.post(f'/api/billing/admin/schools/{self.school.pk}/blocks/',
                                  {'blocks': 0}, format='json').status_code, 400)

    @override_settings(CORS_ALLOWED_ORIGINS=['https://clarriva.com'], PAYSTACK_CALLBACK_URL='https://clarriva.com/d')
    def test_paystack_only_sends_payers_back_to_our_own_sites(self):
        self.assertEqual(safe_callback('https://queens.clarriva.com/dashboard/billing'),
                         'https://queens.clarriva.com/dashboard/billing')
        self.assertEqual(safe_callback('https://evil.example/x'), 'https://clarriva.com/d')
        self.assertEqual(safe_callback('https://clarriva.com.evil.example/x'), 'https://clarriva.com/d')


@override_settings(BILLING_ENFORCE=True)
class RunningExamTest(Base):
    def setUp(self):
        super().setUp()
        self.school.status = 'active'
        self.school.access_until = self.today - timedelta(days=2)        # lapsed
        self.school.save()
        self.student = User.objects.create_user(username='s', email='s@p.test', password=PASSWORD,
                                                role='student', school=self.school)
        self.exam = Exam.objects.create(school=self.school, title='T', status='published', duration_mins=30)
        now = timezone.now()
        self.session = ExamSession.objects.create(exam=self.exam, student=self.student, school=self.school,
                                                  status='active', started_at=now,
                                                  deadline=now + timedelta(minutes=30))

    def allowed(self, path):
        from rest_framework.test import APIRequestFactory
        from .exceptions import BillingBlocked
        try:
            services.enforce(self.student, APIRequestFactory().post(path))
            return True
        except BillingBlocked:
            return False

    def test_a_running_exam_can_be_saved_submitted_and_reopened(self):
        for path in (f'/api/exams/sessions/{self.session.id}/save/',
                     f'/api/exams/sessions/{self.session.id}/submit/',
                     f'/api/exams/exams/{self.exam.id}/start/'):
            self.assertTrue(self.allowed(path), path)

    def test_a_new_exam_cannot_be_started(self):
        other = Exam.objects.create(school=self.school, title='U', status='published', duration_mins=30)
        self.assertFalse(self.allowed(f'/api/exams/exams/{other.id}/start/'))
        self.assertFalse(self.allowed('/api/attendance/'))


class GeneratedPasswordTest(Base):
    def token(self):
        res = APIClient().post('/api/auth/login/', {'email': 'a@p.test', 'password': PASSWORD}, format='json')
        api = APIClient()
        api.credentials(HTTP_AUTHORIZATION='Bearer ' + res.json()['access'])
        return api

    def test_the_account_can_do_nothing_else_until_the_password_is_changed(self):
        self.admin.must_change_password = True
        self.admin.save()
        api = self.token()
        blocked = api.get('/api/students/')
        self.assertEqual(blocked.status_code, 403)
        self.assertEqual(blocked.json()['code'], 'password_change_required')
        self.assertEqual(api.post('/api/auth/admin/create-user/', {}, format='json').status_code, 403)
        self.assertEqual(api.get('/api/auth/me/').status_code, 200)
        done = api.post('/api/auth/change-password/',
                        {'current_password': PASSWORD, 'new_password': 'A-brand-new-pass-77'}, format='json')
        self.assertEqual(done.status_code, 200, done.content)
        self.assertEqual(api.get('/api/students/').status_code, 200)


class AddressAndSettingsTest(Base):
    def signup(self, subdomain):
        cache.clear()
        return APIClient().post('/api/auth/onboard/', {
            'email': f'{abs(hash(subdomain))}@n.test', 'password': 'A-brand-new-pass-77', 'first_name': 'N',
            'last_name': 'O', 'school_name': 'New', 'school_subdomain': subdomain,
            'school_state': 'Lagos', 'school_students': 20}, format='json')

    def test_signup_refuses_reserved_and_taken_addresses(self):
        for bad in ('admin', 'API', 'test', 'api-test', 'P School'):
            self.assertEqual(self.signup(bad).status_code, 400, bad)

    def test_signup_cleans_the_address(self):
        res = self.signup('Bright Stars!')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertTrue(School.objects.filter(subdomain='bright-stars').exists())

    def test_school_addresses_may_call_the_api(self):
        import re
        pattern = settings.CORS_ALLOWED_ORIGIN_REGEXES[0]
        self.assertTrue(re.match(pattern, 'https://queens.clarriva.com') or 'clarriva' not in pattern)
        self.assertFalse(re.match(pattern, f'https://{settings.PLATFORM_DOMAIN}.evil.example'))

    def test_a_school_admin_can_save_settings_but_not_billing_or_status(self):
        res = self.api.patch(f'/api/schools/{self.school.pk}/', {
            'current_term': '2nd Term', 'single_device_students': False,
            'paid_blocks': 99, 'access_until': '2099-01-01', 'status': 'active',
            'subdomain': 'stolen', 'state': 'Kano'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.school.refresh_from_db()
        self.assertEqual((self.school.current_term, self.school.single_device_students), ('2nd Term', False))
        self.assertEqual((self.school.paid_blocks, self.school.access_until, self.school.status,
                          self.school.subdomain, self.school.state), (0, None, 'pending', 'p-school', 'Lagos'))

    def test_other_roles_and_other_schools_cannot_change_a_school(self):
        teacher = User.objects.create_user(username='t', email='t@p.test', password=PASSWORD,
                                           role='teacher', school=self.school)
        api = APIClient()
        api.force_authenticate(user=teacher)
        self.assertEqual(api.patch(f'/api/schools/{self.school.pk}/', {'name': 'x'}, format='json').status_code, 403)
        other = School.objects.create(name='O', subdomain='other-s')
        self.assertEqual(self.api.patch(f'/api/schools/{other.pk}/', {'name': 'x'}, format='json').status_code, 404)


class HealthAndCronTest(TestCase):
    @override_settings(ALLOWED_HOSTS=['api.clarriva.com'], SECURE_SSL_REDIRECT=True)
    def test_the_health_check_answers_the_load_balancer(self):
        res = APIClient().get('/health/', HTTP_HOST='10.0.3.17:8000')
        self.assertEqual(res.status_code, 200)

    @override_settings(CRON_SECRET='from-vercel', BILLING_CRON_SECRET='')
    def test_the_reminder_job_accepts_the_schedulers_secret_only(self):
        url = '/api/billing/cron/reminders/'
        self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION='Bearer from-vercel').status_code, 200)
        self.assertEqual(APIClient().get(url, HTTP_AUTHORIZATION='Bearer wrong').status_code, 404)
        self.assertEqual(APIClient().get(url).status_code, 404)
