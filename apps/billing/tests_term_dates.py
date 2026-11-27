"""Term dates: what the platform admins must enter, how they are chased, and what billing does without them."""
from datetime import date, timedelta
from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.locations.models import State
from apps.schools.models import School
from . import term_dates
from .models import Payment, TermCalendar
from .services import GRACE_DAYS, status_payload

Y, NEXT = '2026/2027', '2027/2028'
T1, T2, T3 = '1st Term', '2nd Term', '3rd Term'
NOTICE = 'https://education.example.gov.ng/calendar'
NOV = date(2026, 11, 26)                                       # a Thursday


class Base(TestCase):
    def setUp(self):
        cache.clear()
        self.lagos = State.objects.create(name='Lagos', code='LA')
        self.kano = State.objects.create(name='Kano', code='KN')
        self.root = User.objects.create_user(username='root', email='root@c.test', password='Strong-pass-123',
                                             role='super_admin', first_name='Ada')
        self.api = APIClient()
        self.api.force_authenticate(user=self.root)

    def school(self, state='Lagos', **extra):
        n = School.objects.count()
        return School.objects.create(name=f'School {n}', subdomain=f'sch-{n}', state=state, **extra)

    def add(self, year, term, when, provisional=False, state=None):
        return TermCalendar.objects.create(state=state or self.lagos, academic_year=year, term=term,
                                           resumes_on=when, provisional=provisional)

    def full_session(self, **kwargs):
        self.add(Y, T1, date(2026, 9, 14), **kwargs)
        self.add(Y, T2, date(2027, 1, 11), **kwargs)
        self.add(Y, T3, date(2027, 4, 26), **kwargs)

    def rows(self):
        return {(r.academic_year, r.term): r for r in TermCalendar.objects.filter(state=self.lagos)}


class WhatIsDueTest(Base):
    def test_a_new_session_needs_its_three_terms_at_once(self):
        self.assertEqual(term_dates.due_dates({}, NOV)[0], [(Y, T1), (Y, T2), (Y, T3)])

    def test_next_sessions_first_term_is_wanted_90_days_before_third_term(self):
        self.full_session()
        due_day = date(2027, 4, 26) - timedelta(days=90)
        self.assertEqual(term_dates.due_dates(self.rows(), due_day - timedelta(days=1)), ([], []))
        self.assertEqual(term_dates.due_dates(self.rows(), due_day), ([(NEXT, T1)], []))

    def test_once_the_next_session_starts_its_own_terms_are_wanted(self):
        self.full_session()
        self.add(NEXT, T1, date(2027, 9, 13))
        missing, _ = term_dates.due_dates(self.rows(), date(2027, 9, 14))
        self.assertEqual(missing, [(NEXT, T2), (NEXT, T3)])

    def test_unconfirmed_dates_are_listed_apart(self):
        self.full_session(provisional=True)
        self.assertEqual(term_dates.due_dates(self.rows(), NOV), ([], [(Y, T1), (Y, T2), (Y, T3)]))

    def test_only_states_with_working_schools_are_chased_and_stateless_schools_are_named(self):
        self.school('lagos')
        self.school('Kano', status='suspended')
        lost = self.school('')
        states, unmatched = term_dates.states_needing_dates(NOV)
        self.assertEqual([s['state'].name for s in states], ['Lagos'])
        self.assertEqual(unmatched, [lost.name])


class DailyEmailTest(Base):
    def run_digest(self, day):
        with patch('apps.billing.term_dates.send_email', return_value=True) as send:
            count = term_dates.send_digest(day)
        return count, send

    def test_missing_dates_are_emailed_every_day_once_a_day_until_entered(self):
        self.school()
        for offset in (0, 1, 2):
            count, send = self.run_digest(NOV + timedelta(days=offset))
            self.assertEqual(count, 1)
            self.assertEqual(self.run_digest(NOV + timedelta(days=offset))[0], 0)     # not twice in a day
        self.full_session()
        self.assertEqual(self.run_digest(NOV + timedelta(days=3))[0], 0)               # resolved: it stops

    def test_one_email_lists_every_state(self):
        self.school('Lagos')
        self.school('Kano')
        _, send = self.run_digest(NOV)
        self.assertEqual(send.call_count, 1)
        text = send.call_args[0][2]
        self.assertIn('Lagos', text)
        self.assertIn('Kano', text)

    def test_a_failed_send_is_tried_again(self):
        self.school()
        with patch('apps.billing.term_dates.send_email', return_value=False):
            self.assertEqual(term_dates.send_digest(NOV), 0)
        self.assertEqual(self.run_digest(NOV)[0], 1)

    def test_unconfirmed_dates_are_emailed_on_mondays_only(self):
        self.school()
        self.full_session(provisional=True)
        self.assertEqual(self.run_digest(NOV)[0], 0)
        self.assertEqual(self.run_digest(date(2026, 11, 30))[0], 1)

    def test_every_admin_gets_it_by_default_including_ones_added_later(self):
        User.objects.create_user(username='new', email='new@c.test', password='Strong-pass-123', role='super_admin')
        User.objects.create_user(username='sa', email='sa@s.test', password='Strong-pass-123', role='school_admin')
        self.assertEqual(term_dates.recipients(), ['new@c.test', 'root@c.test'])

    def test_the_admins_can_choose_who_gets_it_but_never_nobody(self):
        other = User.objects.create_user(username='o', email='o@c.test', password='Strong-pass-123', role='super_admin')
        url = '/api/billing/calendars/recipients/'
        res = self.api.put(url, {'ids': [str(other.pk)]}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(term_dates.recipients(), ['o@c.test'])
        self.assertEqual(self.api.put(url, {'ids': []}, format='json').status_code, 400)
        other.is_active = False                                  # the only chosen admin leaves
        other.save()
        self.assertEqual(term_dates.recipients(), ['root@c.test'])

    def test_the_first_school_in_a_state_raises_the_alarm_at_once(self):
        first = self.school()
        with patch('apps.billing.term_dates.send_email', return_value=True) as send:
            self.assertTrue(term_dates.alert_new_school(first, NOV))
            second = self.school()
            self.assertFalse(term_dates.alert_new_school(second, NOV))
        self.assertEqual(send.call_count, 1)


class EnteringDatesTest(Base):
    def entry(self, year, term, when, **extra):
        return {'academic_year': year, 'term': term, 'resumes_on': when, 'source_url': NOTICE, **extra}

    def four(self):
        return [self.entry(Y, T1, '2026-09-14'), self.entry(Y, T2, '2027-01-11'),
                self.entry(Y, T3, '2027-04-26'), self.entry(NEXT, T1, '2027-09-13', provisional=True,
                                                            source_url='')]

    def bulk(self, dates, states=None, **extra):
        states = states or [str(self.lagos.pk), str(self.kano.pk)]
        return self.api.post('/api/billing/calendars/bulk/', {'states': states, 'dates': dates, **extra},
                             format='json')

    def test_four_dates_entered_once_apply_to_several_states_with_who_confirmed(self):
        res = self.bulk(self.four())
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()['saved'], 8)
        confirmed = TermCalendar.objects.get(state=self.kano, academic_year=Y, term=T1)
        self.assertEqual((confirmed.confirmed_by, confirmed.source_url), (self.root, NOTICE))
        self.assertIsNone(TermCalendar.objects.get(state=self.kano, academic_year=NEXT).confirmed_by)

    def test_saving_again_updates_instead_of_duplicating(self):
        self.bulk(self.four())
        res = self.bulk(self.four())
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(TermCalendar.objects.count(), 8)

    def test_a_confirmed_date_needs_the_notice_link(self):
        res = self.bulk([self.entry(Y, T1, '2026-09-14', source_url='')])
        self.assertEqual(res.status_code, 400)
        self.assertEqual(TermCalendar.objects.count(), 0)

    def test_dates_out_of_order_save_nothing(self):
        res = self.bulk([self.entry(Y, T1, '2026-09-14'), self.entry(Y, T2, '2026-08-01')])
        self.assertEqual(res.json()['code'], 'dates_out_of_order')
        self.assertEqual(TermCalendar.objects.count(), 0)

    def test_an_odd_gap_must_be_confirmed(self):
        odd = [self.entry(Y, T1, '2026-09-14'), self.entry(Y, T2, '2026-10-01')]
        self.assertEqual(self.bulk(odd).json()['code'], 'unusual_gap')
        self.assertEqual(TermCalendar.objects.count(), 0)
        self.assertEqual(self.bulk(odd, confirm_unusual=True).status_code, 200)

    def test_the_single_date_screen_follows_the_same_rules(self):
        body = {'state': str(self.lagos.pk), 'academic_year': Y, 'term': T1, 'resumes_on': '2026-09-14'}
        self.assertEqual(self.api.post('/api/billing/calendars/', body, format='json').status_code, 400)
        ok = self.api.post('/api/billing/calendars/', {**body, 'provisional': True}, format='json')
        self.assertEqual(ok.status_code, 201, ok.content)
        bad = {**body, 'term': T2, 'resumes_on': '2026-09-01', 'provisional': True}
        self.assertEqual(self.api.post('/api/billing/calendars/', bad, format='json').status_code, 400)
        self.assertEqual(self.api.post('/api/billing/calendars/', {**body, 'academic_year': '2026'},
                                       format='json').status_code, 400)

    def test_only_platform_admins_may_enter_dates_or_choose_recipients(self):
        admin = User.objects.create_user(username='sa', email='sa@s.test', password='Strong-pass-123',
                                         role='school_admin', school=self.school())
        api = APIClient()
        api.force_authenticate(user=admin)
        for url in ('/api/billing/calendars/bulk/', '/api/billing/calendars/'):
            self.assertEqual(api.post(url, {}, format='json').status_code, 403)
        for url in ('/api/billing/calendars/recipients/', '/api/billing/calendars/due/'):
            self.assertEqual(api.get(url).status_code, 403)


class PaidOnAnEstimateTest(Base):
    def setUp(self):
        super().setUp()
        self.estimate = date(2027, 1, 11)
        self.row = self.add(Y, T2, self.estimate, provisional=True)
        self.client_school = self.school(access_until=self.estimate + timedelta(days=GRACE_DAYS), paid_blocks=1)
        self.payment = Payment.objects.create(
            school=self.client_school, reference='CLV-est', status='paid', amount=3000000, blocks_after=1,
            academic_year=Y, term=T1, covers_from=date(2026, 9, 14),
            access_until=self.client_school.access_until)

    def confirm(self, when):
        res = self.api.patch(f'/api/billing/calendars/{self.row.pk}/',
                             {'resumes_on': when, 'provisional': False, 'source_url': NOTICE}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.client_school.refresh_from_db()
        self.payment.refresh_from_db()

    def test_a_later_confirmed_date_extends_what_was_paid_for(self):
        self.confirm('2027-01-18')
        expected = date(2027, 1, 18) + timedelta(days=GRACE_DAYS)
        self.assertEqual((self.client_school.access_until, self.payment.access_until), (expected, expected))
        self.assertIn('Extended', self.payment.note)

    def test_an_earlier_confirmed_date_never_shortens(self):
        before = self.client_school.access_until
        self.confirm('2027-01-04')
        self.assertEqual((self.client_school.access_until, self.payment.access_until), (before, before))


class NoDatesNoPaymentTest(Base):
    def test_a_school_cannot_pay_until_its_dates_are_entered(self):
        school = self.school(declared_students=40, status='pending', current_term=T1, current_academic_year=Y)
        admin = User.objects.create_user(username='sa', email='sa@s.test', password='Strong-pass-123',
                                         role='school_admin', school=school)
        payload = status_payload(school)
        self.assertEqual((payload['can_pay'], payload['blocked_reason']), (False, 'missing_calendar'))
        api = APIClient()
        api.force_authenticate(user=admin)
        res = api.post('/api/billing/payments/initialize/', {}, format='json')
        self.assertEqual((res.status_code, res.json()['code']), (400, 'missing_calendar'))
        self.assertEqual(Payment.objects.count(), 0)

    def test_a_provisional_date_entered_by_an_admin_is_enough_to_pay(self):
        today = timezone.localdate()
        school = self.school(declared_students=40, status='pending', current_term=T1, current_academic_year=Y)
        self.add(Y, T1, today - timedelta(days=10))
        self.add(Y, T2, today + timedelta(days=100), provisional=True)
        payload = status_payload(school)
        self.assertTrue(payload['can_pay'])
        self.assertTrue(payload['dates_provisional'])
