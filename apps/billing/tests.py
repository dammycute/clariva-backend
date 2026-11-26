import json
from datetime import date, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import User
from apps.locations.models import State
from apps.schools.models import School
from . import paystack
from .exceptions import PaymentProblem, StudentLimitReached
from .models import Payment, TermCalendar
from .services import (
    GRACE_DAYS, apply_manual_payment, billing_state, blocks_for, capacity, check_capacity,
    fulfil_payment, invalidate, limit_for_blocks, next_term, term_window,
)

TODAY = date(2026, 11, 24)
SECRET = 'sk_test_example'
SIGNING = 'whsec_example'


class BlocksForTests(TestCase):
    def test_table(self):
        expected = {1: 1, 50: 1, 51: 1, 60: 1, 61: 2, 100: 2, 110: 2, 111: 3, 160: 3, 161: 4}
        for students, blocks in expected.items():
            self.assertEqual(blocks_for(students), blocks, students)

    def test_zero_is_refused(self):
        with self.assertRaises(ValueError):
            blocks_for(0)

    def test_limit_includes_the_buffer(self):
        self.assertEqual(limit_for_blocks(1), 60)
        self.assertEqual(limit_for_blocks(2), 110)


class CalendarTests(TestCase):
    def test_next_term_rolls_the_year(self):
        self.assertEqual(next_term('2026/2027', '1st Term'), ('2026/2027', '2nd Term'))
        self.assertEqual(next_term('2026/2027', '3rd Term'), ('2027/2028', '1st Term'))

    def test_window_ends_21_days_after_the_next_resumption(self):
        state = State.objects.create(name='Lagos', code='LA')
        TermCalendar.objects.create(state=state, academic_year='2026/2027', term='2nd Term',
                                    resumes_on=date(2027, 1, 5))
        TermCalendar.objects.create(state=state, academic_year='2026/2027', term='3rd Term',
                                    resumes_on=date(2027, 4, 20))
        school = School.objects.create(name='A', subdomain='a', state='Lagos')
        window = term_window('Lagos', school, '2026/2027', '2nd Term')
        self.assertEqual(window['access_until'], date(2027, 4, 20) + timedelta(days=GRACE_DAYS))

    def test_states_with_different_dates_get_different_ends(self):
        lagos = State.objects.create(name='Lagos', code='LA')
        kano = State.objects.create(name='Kano', code='KN')
        TermCalendar.objects.create(state=lagos, academic_year='2026/2027', term='1st Term',
                                    resumes_on=date(2026, 9, 8))
        TermCalendar.objects.create(state=lagos, academic_year='2026/2027', term='2nd Term',
                                    resumes_on=date(2027, 1, 5))
        TermCalendar.objects.create(state=kano, academic_year='2026/2027', term='1st Term',
                                    resumes_on=date(2026, 9, 15))
        TermCalendar.objects.create(state=kano, academic_year='2026/2027', term='2nd Term',
                                    resumes_on=date(2027, 1, 12))
        school = School.objects.create(name='A', subdomain='a', state='Lagos')
        self.assertEqual(term_window('Lagos', school, '2026/2027', '1st Term')['access_until'],
                         date(2027, 1, 5) + timedelta(days=GRACE_DAYS))
        self.assertEqual(term_window('Kano', school, '2026/2027', '1st Term')['access_until'],
                         date(2027, 1, 12) + timedelta(days=GRACE_DAYS))

    def test_a_school_override_wins(self):
        state = State.objects.create(name='Lagos', code='LA')
        school = School.objects.create(name='A', subdomain='a', state='Lagos')
        TermCalendar.objects.create(state=state, academic_year='2026/2027', term='1st Term',
                                    resumes_on=date(2026, 9, 8))
        TermCalendar.objects.create(state=state, academic_year='2026/2027', term='2nd Term',
                                    resumes_on=date(2027, 1, 5))
        TermCalendar.objects.create(state=state, school=school, academic_year='2026/2027',
                                    term='1st Term', resumes_on=date(2026, 9, 1))
        window = term_window('Lagos', school, '2026/2027', '1st Term')
        self.assertEqual(window['resumes_on'], date(2026, 9, 1))

    def test_missing_dates_mean_no_window(self):
        State.objects.create(name='Lagos', code='LA')
        school = School.objects.create(name='A', subdomain='a', state='Lagos')
        self.assertIsNone(term_window('Lagos', school, '2026/2027', '1st Term'))


class StateTests(TestCase):
    def test_boundaries(self):
        access = date(2027, 1, 26)                     # 21 days after a 5 Jan resumption
        self.assertEqual(billing_state(None, TODAY), 'pending')
        self.assertEqual(billing_state(access, date(2027, 1, 4)), 'active')
        self.assertEqual(billing_state(access, date(2027, 1, 5)), 'grace')
        self.assertEqual(billing_state(access, access), 'grace')
        self.assertEqual(billing_state(access, access + timedelta(days=1)), 'lapsed')


class SignatureTests(TestCase):
    def body(self):
        return json.dumps({'event': 'charge.success'}).encode()

    @override_settings(PAYSTACK_SIGNING_SECRET=SIGNING, PAYSTACK_SECRET_KEY=SECRET)
    def test_current_header_is_accepted(self):
        body = self.body()
        meta = {'HTTP_PAYSTACK_SIGNATURE': paystack.signing_timestamp(SIGNING, body)}
        self.assertTrue(paystack.signature_ok(body, meta))

    @override_settings(PAYSTACK_SIGNING_SECRET=SIGNING, PAYSTACK_SECRET_KEY=SECRET)
    def test_several_v1_values_are_all_checked(self):
        body = self.body()
        good = paystack.signing_timestamp(SIGNING, body)
        header = good.replace(',v1=', ',v1=other:deadbeef,v1=')
        self.assertTrue(paystack.signature_ok(body, {'HTTP_PAYSTACK_SIGNATURE': header}))

    @override_settings(PAYSTACK_SIGNING_SECRET=SIGNING, PAYSTACK_SECRET_KEY=SECRET)
    def test_stale_timestamp_is_refused(self):
        body = self.body()
        old = paystack.signing_timestamp(SIGNING, body, at=None)
        stale = 't=1000000000,v1=' + old.split('v1=')[1]
        self.assertFalse(paystack.signature_ok(body, {'HTTP_PAYSTACK_SIGNATURE': stale}))

    @override_settings(PAYSTACK_SIGNING_SECRET=SIGNING, PAYSTACK_SECRET_KEY=SECRET)
    def test_a_wrong_body_is_refused(self):
        meta = {'HTTP_PAYSTACK_SIGNATURE': paystack.signing_timestamp(SIGNING, self.body())}
        self.assertFalse(paystack.signature_ok(b'{"event":"x"}', meta))

    @override_settings(PAYSTACK_SIGNING_SECRET='', PAYSTACK_SECRET_KEY=SECRET)
    def test_deprecated_header_is_the_fallback(self):
        body = self.body()
        meta = {'HTTP_X_PAYSTACK_SIGNATURE': paystack.legacy_signature(SECRET, body)}
        self.assertTrue(paystack.signature_ok(body, meta))

    @override_settings(PAYSTACK_SIGNING_SECRET=SIGNING, PAYSTACK_SECRET_KEY=SECRET)
    def test_new_header_wins_over_the_old_one(self):
        body = self.body()
        meta = {
            'HTTP_PAYSTACK_SIGNATURE': paystack.signing_timestamp(SIGNING, body),
            'HTTP_X_PAYSTACK_SIGNATURE': paystack.legacy_signature(SECRET, body),
        }
        self.assertTrue(paystack.signature_ok(body, meta))
        # If the new-style check fails, a good secret-key signature still proves the sender.
        meta['HTTP_PAYSTACK_SIGNATURE'] = 't=1,v1=nope'
        self.assertTrue(paystack.signature_ok(body, meta))
        meta['HTTP_X_PAYSTACK_SIGNATURE'] = 'nope'
        self.assertFalse(paystack.signature_ok(body, meta))

    @override_settings(PAYSTACK_SIGNING_SECRET='', PAYSTACK_SECRET_KEY='')
    def test_nothing_configured_means_nothing_passes(self):
        self.assertFalse(paystack.signature_ok(self.body(), {}))


class PaymentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(
            name='A', subdomain='a', status='pending', declared_students=55,
        )
        self.payment = Payment.objects.create(
            school=self.school, reference='CLV-1-abc', kind='new', amount=30000 * 100,
            blocks_after=1, students_at_payment=55, academic_year='2026/2027',
            term='1st Term', covers_from=date(2026, 9, 8), access_until=date(2027, 1, 26),
        )

    def success(self, **extra):
        payload = {'status': 'success', 'amount': 30000 * 100, 'currency': 'NGN',
                   'reference': self.payment.reference, 'channel': 'card'}
        payload.update(extra)
        return payload

    def test_a_good_payment_activates_the_school(self):
        paid = fulfil_payment(self.payment, self.success())
        self.assertEqual(paid.status, 'paid')
        self.school.refresh_from_db()
        self.assertEqual(self.school.paid_blocks, 1)
        self.assertEqual(self.school.access_until, date(2027, 1, 26))
        self.assertEqual(self.school.status, 'active')

    def test_a_second_delivery_creates_one_result(self):
        fulfil_payment(self.payment, self.success())
        again = fulfil_payment(self.payment, self.success())
        self.assertEqual(again.status, 'paid')
        self.assertEqual(Payment.objects.filter(school=self.school, status='paid').count(), 1)

    def test_a_wrong_amount_is_refused(self):
        with self.assertRaises(PaymentProblem):
            fulfil_payment(self.payment, self.success(amount=100))

    def test_a_failed_charge_is_refused(self):
        with self.assertRaises(PaymentProblem):
            fulfil_payment(self.payment, self.success(status='failed'))

    def test_a_payment_does_not_un_suspend_a_school(self):
        self.school.status = 'suspended'
        self.school.save(update_fields=['status'])
        fulfil_payment(self.payment, self.success())
        self.school.refresh_from_db()
        self.assertEqual(self.school.status, 'suspended')

    def test_saved_dates_do_not_move_with_the_calendar(self):
        fulfil_payment(self.payment, self.success())
        state = State.objects.create(name='Lagos', code='LA')
        TermCalendar.objects.create(state=state, academic_year='2026/2027', term='1st Term',
                                    resumes_on=date(2026, 10, 1))
        self.school.refresh_from_db()
        self.assertEqual(self.school.access_until, date(2027, 1, 26))


class CapacityTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(name='A', subdomain='a', paid_blocks=1)

    @override_settings(BILLING_ENFORCE=True)
    def test_the_buffer_lets_the_sixtieth_in(self):
        from apps.students.models import StudentProfile
        for i in range(59):
            user = User.objects.create(username=f's{i}', school=self.school, role='student')
            StudentProfile.objects.create(user=user, school=self.school, student_status='active')
        self.assertEqual(capacity(self.school)['remaining'], 1)
        check_capacity(self.school, 1)                   # the 60th is allowed
        with self.assertRaises(StudentLimitReached):
            check_capacity(self.school, 2)

    @override_settings(BILLING_ENFORCE=False)
    def test_nothing_is_limited_while_billing_is_dark(self):
        check_capacity(self.school, 500)

    @override_settings(BILLING_ENFORCE=True)
    def test_an_unpaid_school_is_left_to_the_402_gate(self):
        school = School.objects.create(name='B', subdomain='b')
        check_capacity(school, 500)


class EnforcementTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(name='A', subdomain='a', status='pending')
        self.user = User.objects.create_user(
            username='admin@a.test', email='admin@a.test', password='pw12345678',
            school=self.school, role='school_admin',
        )
        self.client = APIClient()
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def tearDown(self):
        cache.clear()

    @override_settings(BILLING_ENFORCE=True)
    def test_a_pending_school_sees_only_billing(self):
        res = self.client.get('/api/students/')
        self.assertEqual(res.status_code, 402)
        self.assertEqual(res.json()['code'], 'billing_pending')
        # The billing page itself and the school's own detail keep working.
        self.assertEqual(self.client.get('/api/billing/status/').status_code, 200)
        self.assertEqual(self.client.get(f'/api/schools/{self.school.pk}/').status_code, 200)

    @override_settings(BILLING_ENFORCE=True)
    def test_grace_is_full_access(self):
        self.school.status = 'active'
        self.school.access_until = timezone.localdate() + timedelta(days=3)
        self.school.save()
        invalidate(self.school.pk)
        self.assertEqual(self.client.get('/api/students/').status_code, 200)
        res = self.client.post('/api/students/', {'first_name': 'A', 'last_name': 'B'},
                               format='json')
        self.assertNotEqual(res.status_code, 402)

    @override_settings(BILLING_ENFORCE=True)
    def test_lapsed_reads_but_cannot_write(self):
        self.school.status = 'active'
        self.school.access_until = date(2020, 1, 1)
        self.school.save()
        invalidate(self.school.pk)
        self.assertEqual(self.client.get('/api/students/').status_code, 200)
        res = self.client.post('/api/students/', {'first_name': 'A', 'last_name': 'B'},
                               format='json')
        self.assertEqual(res.status_code, 402)
        self.assertEqual(res.json()['code'], 'billing_lapsed')

    @override_settings(BILLING_ENFORCE=False)
    def test_dark_mode_blocks_nothing(self):
        self.assertEqual(self.client.get('/api/students/').status_code, 200)


class WebhookTests(TestCase):
    def setUp(self):
        cache.clear()
        self.school = School.objects.create(name='A', subdomain='a', status='pending')
        self.payment = Payment.objects.create(
            school=self.school, reference='CLV-1-hook', kind='new', amount=30000 * 100,
            blocks_after=1, students_at_payment=55, academic_year='2026/2027',
            term='1st Term', covers_from=date(2026, 9, 8), access_until=date(2027, 1, 26),
        )
        self.client = APIClient()

    def post(self, body, signature):
        return self.client.post(
            '/api/billing/webhook/', data=body, content_type='application/json',
            HTTP_PAYSTACK_SIGNATURE=signature,
        )

    @override_settings(PAYSTACK_SIGNING_SECRET=SIGNING, PAYSTACK_SECRET_KEY=SECRET)
    def test_a_bad_signature_is_refused(self):
        body = json.dumps({'event': 'charge.success', 'data': {'reference': 'CLV-1-hook'}})
        res = self.post(body, 't=1,v1=deadbeef')
        self.assertEqual(res.status_code, 401)
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, 'pending')

    @override_settings(PAYSTACK_SIGNING_SECRET=SIGNING, PAYSTACK_SECRET_KEY=SECRET)
    def test_a_good_delivery_settles_the_payment(self):
        body = json.dumps({'event': 'charge.success', 'data': {'reference': 'CLV-1-hook'}})
        signature = paystack.signing_timestamp(SIGNING, body.encode())
        verified = {'status': 'success', 'amount': 30000 * 100, 'currency': 'NGN',
                    'reference': 'CLV-1-hook'}
        with patch('apps.billing.paystack.verify', return_value=verified):
            res = self.post(body, signature)
            self.assertEqual(res.status_code, 200)
            again = self.post(body, signature)
        self.assertEqual(again.status_code, 200)
        self.assertTrue(again.json().get('duplicate'))
        self.assertEqual(Payment.objects.filter(status='paid').count(), 1)


class ManualPaymentTests(TestCase):
    def setUp(self):
        cache.clear()
        self.state = State.objects.create(name='Lagos', code='LA')
        TermCalendar.objects.create(state=self.state, academic_year='2026/2027',
                                    term='1st Term', resumes_on=date(2026, 9, 8))
        TermCalendar.objects.create(state=self.state, academic_year='2026/2027',
                                    term='2nd Term', resumes_on=date(2027, 1, 5))
        self.school = School.objects.create(name='A', subdomain='a', state='Lagos',
                                            status='pending', declared_students=100)

    def test_a_grant_uses_the_calendar(self):
        payment = apply_manual_payment(
            school=self.school, blocks=2, academic_year='2026/2027', term='1st Term',
            access_until=date(2027, 1, 26), covers_from=date(2026, 9, 8),
            amount=60000 * 100, kind='grant', note='Opening cover', user=None,
        )
        self.assertEqual(payment.status, 'paid')
        self.school.refresh_from_db()
        self.assertEqual(self.school.access_until, date(2027, 1, 26))
        self.assertEqual(self.school.status, 'active')
        self.assertEqual(self.school.paid_blocks, 2)
