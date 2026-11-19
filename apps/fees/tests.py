"""Fees are billed automatically: a fee item creates invoices for the students it applies to."""
from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.classes.models import Class
from apps.schools.models import School
from apps.students.models import StudentProfile
from .models import FeeInvoice, FeeInvoiceItem


class AutoInvoiceTest(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='Queens', subdomain='queens-fee',
                                            current_term='1st Term', current_academic_year='2025/2026')
        self.jss1a = Class.objects.create(school=self.school, name='JSS1A', year_group='JSS1', arm='A')
        self.jss1b = Class.objects.create(school=self.school, name='JSS1B', year_group='JSS1', arm='B')
        self.jss2a = Class.objects.create(school=self.school, name='JSS2A', year_group='JSS2', arm='A')
        self.admin = User.objects.create_user(username='adm', email='a@t.com', password='pass1234',
                                              school=self.school, role='school_admin')
        self.api = APIClient()
        self.api.force_authenticate(user=self.admin)
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

    def test_a_new_fee_bills_only_the_students_it_applies_to(self):
        self._fee()
        self.assertEqual(FeeInvoice.objects.filter(student__in=[self.s1, self.s2]).count(), 2)
        self.assertFalse(FeeInvoice.objects.filter(student=self.s3).exists())      # JSS2 is not billed
        inv = FeeInvoice.objects.get(student=self.s1)
        self.assertEqual(inv.amount_due, Decimal('79400.00'))
        self.assertEqual(FeeInvoiceItem.objects.filter(invoice=inv).count(), 1)

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
        res = self.api.post('/api/students/', {'first_name': 'New', 'last_name': 'Kid',
                                               'class_group': str(self.jss1a.id)}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        self.assertEqual(FeeInvoice.objects.filter(student_id=res.json()['id']).count(), 1)

    def test_imported_students_are_billed(self):
        self._fee()
        res = self.api.post('/api/students/import_csv/', {'csv': 'full_name,class\nAda Obi,JSS1A\nBayo Ade,JSS2A\n'},
                            format='json')
        self.assertEqual(res.json()['created'], 2, res.content)
        self.assertEqual(FeeInvoice.objects.filter(student__first_name='Ada').count(), 1)
        self.assertEqual(FeeInvoice.objects.filter(student__first_name='Bayo').count(), 0)

    def test_promoting_a_student_into_a_billed_class_bills_them(self):
        self._fee()
        res = self.api.post('/api/students/promote/', {'student_ids': [str(self.s3.id)],
                                                       'target_class_id': str(self.jss1a.id)}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(FeeInvoice.objects.filter(student=self.s3).exists())
