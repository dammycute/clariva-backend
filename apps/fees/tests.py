"""Fees are billed automatically: a fee item creates invoices for the students it applies to."""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.classes.models import Class
from apps.schools.models import School
from apps.students.models import StudentProfile
from .models import FeeInvoice, FeeInvoiceItem


class FeeBase(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Queens', subdomain='queens-fee',
                                            current_term='1st Term', current_academic_year='2025/2026')
        self.jss1a = Class.objects.create(school=self.school, name='JSS1A', year_group='JSS1', arm='A')
        self.jss1b = Class.objects.create(school=self.school, name='JSS1B', year_group='JSS1', arm='B')
        self.jss2a = Class.objects.create(school=self.school, name='JSS2A', year_group='JSS2', arm='A')
        self.admin = User.objects.create_user(username='adm', email='a@t.com', password='pass1234',
                                              school=self.school, role='school_admin')
        self.bursar = User.objects.create_user(username='bur', email='b@t.com', password='pass1234',
                                               school=self.school, role='bursary')
        self.api = APIClient()
        self.api.force_authenticate(user=self.bursar)
        self.admin_api = APIClient()                     # students and notices stay with the admin
        self.admin_api.force_authenticate(user=self.admin)
        self.s1 = self._student('s1', 'ADM1', self.jss1a)
        self.s2 = self._student('s2', 'ADM2', self.jss1b)
        self.s3 = self._student('s3', 'ADM3', self.jss2a)

    def _student(self, username, adm, cls, status='active'):
        user = User.objects.create(school=self.school, username=username, first_name=username, role='student')
        StudentProfile.objects.create(school=self.school, user=user, admission_no=adm, class_group=cls,
                                      student_status=status)
        return user

    def _fee(self, **extra):
        body = {'name': 'Tuition Fee', 'amount': '79400', 'year_group': 'JSS1',
                'term': '1st Term', 'academic_year': '2025/2026', 'is_mandatory': True, **extra}
        res = self.api.post('/api/fees/items/', body, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        return res.json()



class FeeRoleTest(FeeBase):
    def as_role(self, role):
        user = User.objects.create(username=f'x-{role}', school=self.school, role=role)
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_school_leaders_see_fees_but_cannot_change_them(self):
        item = self._fee()
        invoice = FeeInvoice.objects.get(student=self.s1)
        for role in ('school_admin', 'admin_officer', 'principal'):
            client = self.as_role(role)
            for path in ('/api/fees/items/', '/api/fees/invoices/', '/api/fees/bursary-summary/'):
                self.assertEqual(client.get(path).status_code, 200, (role, path))
            attempts = [
                client.post('/api/fees/items/', {'name': 'New', 'amount': '1'}, format='json'),
                client.patch(f"/api/fees/items/{item['id']}/", {'amount': '1'}, format='json'),
                client.delete(f"/api/fees/items/{item['id']}/?with_invoices=true"),
                client.post('/api/fees/invoices/', {'student': str(self.s3.id), 'amount_due': '1'}, format='json'),
                client.patch(f'/api/fees/invoices/{invoice.id}/', {'amount_paid': '1'}, format='json'),
                client.delete(f'/api/fees/invoices/{invoice.id}/'),
            ]
            self.assertEqual([r.status_code for r in attempts], [403] * len(attempts), role)

    def test_teachers_and_students_cannot_read_school_fees(self):
        self._fee()
        for client in (self.as_role('teacher'), self.as_role('student')):
            for path in ('/api/fees/items/', '/api/fees/invoices/', '/api/fees/bursary-summary/'):
                self.assertEqual(client.get(path).status_code, 403, path)


class AutoInvoiceTest(FeeBase):
    def test_a_new_fee_bills_only_the_students_it_applies_to(self):
        self._fee()
        self.assertEqual(FeeInvoice.objects.filter(student__in=[self.s1, self.s2]).count(), 2)
        self.assertFalse(FeeInvoice.objects.filter(student=self.s3).exists())      # JSS2 is not billed
        inv = FeeInvoice.objects.get(student=self.s1)
        self.assertEqual(inv.amount_due, Decimal('79400.00'))
        self.assertEqual(FeeInvoiceItem.objects.filter(invoice=inv).count(), 1)

    def test_billing_many_students_takes_a_handful_of_queries(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from apps.fees.models import FeeItem
        from apps.fees.services import FeeService
        for n in range(40):
            self._student(f'bulk{n}', f'BULK{n}', self.jss1a)
        item = FeeItem.objects.create(school=self.school, name='Tuition Fee', amount=1000, year_group='JSS1',
                                      term='1st Term', academic_year='2025/2026')
        with CaptureQueriesContext(connection) as ctx:
            made = FeeService.invoice_students_for_item(item)
        self.assertEqual(made, 42)                       # 40 new + s1 and s2
        self.assertLess(len(ctx), 15)                    # not one-or-more queries per student

    def test_invoices_can_be_filtered_by_class_and_say_which_class(self):
        self._fee()
        res = self.api.get('/api/fees/invoices/', {'class_group': str(self.jss1a.id)})
        rows = res.json()['results']
        self.assertEqual([r['student'] for r in rows], [str(self.s1.id)])
        self.assertEqual(rows[0]['class_name'], 'JSS1A')
        self.assertEqual(rows[0]['class_group'], str(self.jss1a.id))

    def test_creating_an_announcement_works(self):
        res = self.admin_api.post('/api/comms/', {'title': 'Hi', 'body': 'School resumes'}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        from apps.comms.models import Announcement
        ann = Announcement.objects.get(title='Hi')
        self.assertEqual(ann.school, self.school)
        self.assertEqual(ann.created_by, self.admin)

    def test_the_invoices_show_up_for_the_student_page(self):
        self._fee()
        res = self.api.get('/api/fees/invoices/', {'student_id': str(self.s1.id)})
        self.assertEqual(res.status_code, 200)
        body = res.json()
        rows = body['results'] if isinstance(body, dict) else body
        self.assertEqual(len(rows), 1)

    def test_saving_the_fee_again_does_not_double_bill(self):
        item = self._fee()
        self.api.patch(f"/api/fees/items/{item['id']}/", {'name': 'Tuition'}, format='json')
        self.assertEqual(FeeInvoice.objects.filter(student=self.s1).count(), 1)

    def test_saving_again_bills_students_added_since(self):
        item = self._fee()
        late = self._student('late', 'ADM9', self.jss1a)
        self.assertFalse(FeeInvoice.objects.filter(student=late).exists())
        self.api.patch(f"/api/fees/items/{item['id']}/", {'name': 'Tuition'}, format='json')
        self.assertTrue(FeeInvoice.objects.filter(student=late).exists())

    def test_a_fee_for_another_term_is_not_billed_yet(self):
        self._fee(term='2nd Term')
        self.assertEqual(FeeInvoice.objects.count(), 0)

    def test_an_optional_fee_is_not_billed_automatically(self):
        self._fee(is_mandatory=False)
        self.assertEqual(FeeInvoice.objects.count(), 0)

    def test_inactive_students_are_not_billed(self):
        gone = self._student('gone', 'ADM8', self.jss1a, status='graduated')
        self._fee()
        self.assertFalse(FeeInvoice.objects.filter(student=gone).exists())

    def test_tiered_prices_use_the_students_year_group(self):
        self._fee(year_group=None, pricing_tiers={'JSS1': 50000, 'JSS2': 60000}, amount='1')
        self.assertEqual(FeeInvoice.objects.get(student=self.s1).amount_due, Decimal('50000.00'))
        self.assertEqual(FeeInvoice.objects.get(student=self.s3).amount_due, Decimal('60000.00'))

    def test_a_student_added_later_is_billed_straight_away(self):
        self._fee()
        res = self.admin_api.post('/api/students/', {'first_name': 'New', 'last_name': 'Kid',
                                               'class_group': str(self.jss1a.id)}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(FeeInvoice.objects.filter(student_id=res.json()['id']).count(), 1)

    def test_imported_students_are_billed(self):
        self._fee()
        res = self.admin_api.post('/api/students/import_csv/', {'csv': 'full_name,class\nAda Obi,JSS1A\nBayo Ade,JSS2A\n'},
                            format='json')
        self.assertEqual(res.json()['created'], 2, res.content)
        self.assertEqual(FeeInvoice.objects.filter(student__first_name='Ada').count(), 1)
        self.assertEqual(FeeInvoice.objects.filter(student__first_name='Bayo').count(), 0)

    def test_promoting_a_student_into_a_billed_class_bills_them(self):
        self._fee()
        res = self.admin_api.post('/api/students/promote/', {'student_ids': [str(self.s3.id)],
                                                       'target_class_id': str(self.jss1a.id)}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(FeeInvoice.objects.filter(student=self.s3).exists())


class SafeFeeDeleteTest(FeeBase):
    """Deleting a fee: its unpaid invoices go with it on request; paid ones are never deleted."""

    def setUp(self):
        super().setUp()
        self.item = self._fee()                              # bills s1 and s2
        self.url = f"/api/fees/items/{self.item['id']}/"

    def test_impact_counts_invoices_and_payments(self):
        res = self.api.get(self.url + 'delete_impact/')
        self.assertEqual(res.json(), {'invoices': 2, 'with_payments': 0})

    def test_plain_delete_asks_what_to_do_with_the_invoices(self):
        res = self.api.delete(self.url)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()['invoices'], 2)
        self.assertEqual(FeeInvoice.objects.count(), 2)      # nothing was deleted

    def test_delete_with_invoices_removes_the_fee_and_its_unpaid_invoices(self):
        res = self.api.delete(self.url + '?with_invoices=true')
        self.assertEqual(res.status_code, 204, res.content)
        self.assertEqual(FeeInvoice.objects.count(), 0)
        self.assertEqual(FeeInvoiceItem.objects.count(), 0)
        self.assertEqual(self.api.get('/api/fees/items/').json()['results'] if isinstance(
            self.api.get('/api/fees/items/').json(), dict) else self.api.get('/api/fees/items/').json(), [])

    def test_keep_invoices_leaves_them_as_before(self):
        res = self.api.delete(self.url + '?keep_invoices=true')
        self.assertEqual(res.status_code, 204)
        self.assertEqual(FeeInvoice.objects.count(), 2)

    def test_an_invoice_with_a_payment_blocks_the_delete(self):
        inv = FeeInvoice.objects.get(student=self.s1)
        inv.amount_paid = Decimal('1000')
        inv.status = 'partial'
        inv.save()
        res = self.api.delete(self.url + '?with_invoices=true')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(FeeInvoice.objects.count(), 2)      # nothing removed, not even the unpaid one
        self.assertTrue(self.api.get(self.url).status_code == 200)    # and the fee still exists

    def test_a_fee_nobody_was_billed_for_deletes_normally(self):
        item = self._fee(name='Uniform', year_group='SS3')   # no SS3 class, so nobody is billed
        self.assertEqual(self.api.delete(f"/api/fees/items/{item['id']}/").status_code, 204)

    def test_a_bundled_invoice_keeps_its_other_fees(self):
        self._fee(name='Books', amount='5000')               # joins the Tuition invoice of s1 and s2
        tuition = FeeInvoice.objects.get(student=self.s1)
        self.assertEqual(tuition.items.count(), 2)
        res = self.api.delete(self.url + '?with_invoices=true')
        self.assertEqual(res.status_code, 204, res.content)
        tuition.refresh_from_db()
        self.assertEqual(tuition.amount_due, Decimal('5000.00'))          # only Books is left on it
        self.assertEqual(FeeInvoiceItem.objects.filter(invoice=tuition).count(), 1)


class CompoundInvoiceTest(FeeBase):
    """A student's fees add up on one invoice instead of one invoice per fee."""

    def test_a_second_fee_joins_the_existing_invoice(self):
        self._fee()                                                       # Tuition for JSS1
        self._fee(name='Interhouse', amount='2000', year_group=None)      # for everyone
        invoices = FeeInvoice.objects.filter(student=self.s1)
        self.assertEqual(invoices.count(), 1)
        inv = invoices.get()
        self.assertEqual(inv.amount_due, Decimal('81400.00'))
        self.assertEqual(sorted(l.fee_item.name for l in inv.items.all()), ['Interhouse', 'Tuition Fee'])

    def test_a_student_with_no_invoice_yet_gets_a_new_one(self):
        self._fee()
        self._fee(name='Interhouse', amount='2000', year_group=None)      # JSS2 student s3 had nothing
        inv = FeeInvoice.objects.get(student=self.s3)
        self.assertEqual(inv.amount_due, Decimal('2000.00'))
        self.assertEqual(FeeInvoice.objects.count(), 3)                   # one per student

    def test_a_part_paid_invoice_still_takes_the_new_fee(self):
        self._fee()
        inv = FeeInvoice.objects.get(student=self.s1)
        inv.amount_paid, inv.status = Decimal('10000'), 'partial'
        inv.save()
        self._fee(name='Interhouse', amount='2000', year_group=None)
        inv.refresh_from_db()
        self.assertEqual(FeeInvoice.objects.filter(student=self.s1).count(), 1)
        self.assertEqual(inv.amount_due, Decimal('81400.00'))
        self.assertEqual(inv.amount_paid, Decimal('10000.00'))

    def test_a_fully_paid_invoice_is_left_alone(self):
        self._fee()
        inv = FeeInvoice.objects.get(student=self.s1)
        inv.amount_paid, inv.status = inv.amount_due, 'paid'
        inv.save()
        self._fee(name='Interhouse', amount='2000', year_group=None)
        inv.refresh_from_db()
        self.assertEqual(inv.amount_due, Decimal('79400.00'))             # the receipt did not change
        self.assertEqual(FeeInvoice.objects.filter(student=self.s1).count(), 2)

    def test_several_fees_for_one_new_student_make_one_invoice(self):
        self._fee()
        self._fee(name='Interhouse', amount='2000', year_group=None)
        from apps.fees.services import FeeService
        new = self._student('s9', 'ADM9', self.jss1a)
        FeeService.invoice_student(new)
        inv = FeeInvoice.objects.get(student=new)
        self.assertEqual(inv.items.count(), 2)
        self.assertEqual(inv.amount_due, Decimal('81400.00'))

    def test_saving_a_fee_again_changes_nothing(self):
        self._fee()
        item = self._fee(name='Interhouse', amount='2000', year_group=None)
        self.api.patch(f"/api/fees/items/{item['id']}/", {'amount': '2000'}, format='json')
        inv = FeeInvoice.objects.get(student=self.s1)
        self.assertEqual(inv.items.count(), 2)
        self.assertEqual(inv.amount_due, Decimal('81400.00'))

    def test_deleting_one_fee_leaves_the_other_on_the_invoice(self):
        tuition = self._fee()
        self._fee(name='Interhouse', amount='2000', year_group=None)
        res = self.api.delete(f"/api/fees/items/{tuition['id']}/?with_invoices=true")
        self.assertEqual(res.status_code, 204, res.content)
        inv = FeeInvoice.objects.get(student=self.s1)
        self.assertEqual(inv.amount_due, Decimal('2000.00'))
        self.assertEqual(inv.items.count(), 1)

    def test_old_duplicate_invoices_can_be_merged(self):
        from apps.fees.models import FeeItem
        from apps.fees.services import FeeService
        tuition = FeeItem.objects.create(school=self.school, name='Tuition', amount=1000, term='1st Term',
                                         academic_year='2025/2026')
        house = FeeItem.objects.create(school=self.school, name='Interhouse', amount=200, term='1st Term',
                                       academic_year='2025/2026')
        for item in (tuition, house):                                      # the old way: one invoice each
            inv = FeeInvoice.objects.create(school=self.school, student=self.s1, fee_item=item,
                                            amount_due=item.amount, status='unpaid')
            FeeInvoiceItem.objects.create(invoice=inv, fee_item=item, amount_due=item.amount)
        paid = FeeInvoice.objects.create(school=self.school, student=self.s2, fee_item=tuition,
                                         amount_due=1000, amount_paid=1000, status='paid')
        self.assertEqual(FeeService.merge_open_invoices(self.school), {'students': 1, 'invoices_removed': 1})
        self.assertEqual(FeeInvoice.objects.filter(student=self.s1).count(), 2)       # a preview changes nothing
        FeeService.merge_open_invoices(self.school, apply=True)
        inv = FeeInvoice.objects.get(student=self.s1)
        self.assertEqual(inv.amount_due, Decimal('1200.00'))
        self.assertEqual(inv.items.count(), 2)
        paid.refresh_from_db()
        self.assertEqual(paid.amount_paid, Decimal('1000.00'))                         # money records untouched
