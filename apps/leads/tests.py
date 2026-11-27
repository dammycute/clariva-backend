import json
from unittest import mock

from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.accounts.models import User

from .models import DemoRequest

URL = '/api/leads/demo/'
GOOD = {'name': 'Ngozi Bello', 'school_name': 'Queens College', 'role': 'principal',
        'phone': '0803 123 4567', 'email': 'ngozi@example.com', 'students': 240, 'message': 'We want to see CBT.'}
MAIL = dict(RESEND_API_KEY='re_test', DEMO_NOTIFY_EMAIL='owner@example.com', DEMO_FROM_EMAIL='Clariva <onboarding@resend.dev>')


class DemoRequestTest(TestCase):
    def setUp(self):
        cache.clear()                              # the rate limit counts across tests otherwise

    def post(self, data, **extra):
        return APIClient().post(URL, data, format='json', **extra)

    def test_a_request_is_saved(self):
        res = self.post(GOOD)
        self.assertEqual(res.status_code, 201)
        lead = DemoRequest.objects.get()
        self.assertEqual((lead.school_name, lead.students, lead.phone), ('Queens College', 240, '0803 123 4567'))

    def test_email_and_students_are_optional(self):
        res = self.post({'name': 'A', 'school_name': 'B', 'phone': '07066752449'})
        self.assertEqual(res.status_code, 201)

    def test_bad_input_is_refused(self):
        for bad in ({**GOOD, 'phone': 'abc'}, {**GOOD, 'email': 'nope'}, {**GOOD, 'name': ''}, {**GOOD, 'students': 0},
                    {**GOOD, 'role': 'hacker'}):
            self.assertEqual(self.post(bad).status_code, 400, bad)
        self.assertEqual(DemoRequest.objects.count(), 0)

    def test_a_filled_bot_trap_looks_successful_but_saves_nothing(self):
        self.assertEqual(self.post({**GOOD, 'website': 'http://spam.example'}).status_code, 201)
        self.assertEqual(DemoRequest.objects.count(), 0)

    def test_a_stale_sign_in_header_does_not_block_the_public_form(self):
        res = self.post(GOOD, HTTP_AUTHORIZATION='Bearer not-a-real-token')
        self.assertEqual(res.status_code, 201)

    @override_settings(**MAIL)
    def test_the_owner_is_emailed_through_resend(self):
        with mock.patch('apps.base.mail.urlopen') as sent:
            self.post(GOOD)
        req = sent.call_args[0][0]
        body = json.loads(req.data)
        self.assertEqual(req.full_url, 'https://api.resend.com/emails')
        self.assertEqual(req.get_header('Authorization'), 'Bearer re_test')
        self.assertEqual(req.get_header('User-agent'), 'clariva-backend')
        self.assertEqual(body['to'], ['owner@example.com'])
        self.assertEqual(body['reply_to'], 'ngozi@example.com')
        self.assertIn('Queens College', body['subject'])
        self.assertIn('0803 123 4567', body['text'])
        self.assertTrue(DemoRequest.objects.get().emailed)

    @override_settings(**MAIL)
    def test_a_failing_email_does_not_lose_the_request(self):
        with mock.patch('apps.base.mail.urlopen', side_effect=OSError('down')):
            res = self.post(GOOD)
        self.assertEqual(res.status_code, 201)
        self.assertFalse(DemoRequest.objects.get().emailed)

    @override_settings(RESEND_API_KEY='', DEMO_NOTIFY_EMAIL='')
    def test_without_email_settings_nothing_is_sent(self):
        with mock.patch('apps.base.mail.urlopen') as sent:
            self.assertEqual(self.post(GOOD).status_code, 201)
        sent.assert_not_called()

    @override_settings(RESEND_API_KEY='re_test', DEMO_NOTIFY_EMAIL='')
    def test_platform_admins_are_emailed_when_no_address_is_configured(self):
        User.objects.create_user(username='owner', email='owner@example.com',
                                 password='owner-pass-1', role='super_admin')
        with mock.patch('apps.base.mail.urlopen') as sent:
            self.assertEqual(self.post(GOOD).status_code, 201)
        self.assertEqual(json.loads(sent.call_args[0][0].data)['to'], ['owner@example.com'])
        self.assertTrue(DemoRequest.objects.get().emailed)

    def test_a_sixth_request_in_an_hour_is_refused(self):
        codes = [self.post(GOOD).status_code for _ in range(6)]
        self.assertEqual(codes, [201] * 5 + [429])
