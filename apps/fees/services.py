from django.db import models, transaction

from apps.accounts.models import User
from .models import FeeItem, FeeInvoice, FeeInvoiceItem


class FeeService:

    @staticmethod
    @transaction.atomic
    def generate_invoices_for_class(school, class_id, term, academic_year, created_by):
        students = User.objects.filter(
            school=school,
            role='student',
            student_profile__class_group_id=class_id,
            student_profile__student_status='active',
        )
        fee_items = FeeItem.objects.filter(
            school=school,
            term=term,
            academic_year=academic_year,
        ).filter(
            models.Q(class_group_id=class_id) |
            models.Q(year_group__isnull=False) |
            models.Q(class_group_id__isnull=True, year_group__isnull=True)
        )

        created = 0
        for student in students:
            sp = getattr(student, 'student_profile', None)
            year_group = sp.class_group.year_group if sp and sp.class_group else None
            for item in fee_items:
                if item.class_group_id and item.class_group_id != class_id:
                    continue
                if item.year_group and item.year_group != year_group:
                    continue
                if item.arm and sp and sp.class_group and sp.class_group.arm != item.arm:
                    continue

                amount = item.amount
                if item.pricing_tiers and year_group and year_group in item.pricing_tiers:
                    amount = item.pricing_tiers[year_group]

                invoice, inv_created = FeeInvoice.objects.get_or_create(
                    student=student,
                    fee_item=item,
                    defaults={
                        'school': school,
                        'amount_due': amount,
                        'status': 'unpaid',
                    },
                )
                if inv_created:
                    FeeInvoiceItem.objects.create(
                        invoice=invoice,
                        fee_item=item,
                        amount_due=amount,
                    )
                    created += 1

        return created
