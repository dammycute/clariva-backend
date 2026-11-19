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

    # -- Automatic invoices ---------------------------------------
    # A fee item is a price. Students are only billed once they have an invoice, so these
    # create the missing invoices whenever a fee is added or a student joins a class.

    @staticmethod
    def _applies(item, cls):
        """Does this fee item apply to a student in class cls?"""
        if item.class_group_id:
            return bool(cls) and item.class_group_id == cls.id
        year_group = cls.year_group if cls else None
        if item.year_group and not (year_group and year_group.startswith(item.year_group)):
            return False
        if item.arm and not (cls and cls.arm == item.arm):
            return False
        return True

    @staticmethod
    def _is_current(item, school):
        """Only bill fees for the school's current term and year (a blank term or year means any)."""
        return ((not item.term or item.term == school.current_term)
                and (not item.academic_year or item.academic_year == school.current_academic_year))

    @staticmethod
    def _amount(item, cls):
        year_group = cls.year_group if cls else None
        if item.pricing_tiers and year_group in item.pricing_tiers:
            return item.pricing_tiers[year_group]
        return item.amount

    @staticmethod
    def _ensure_invoice(student, item, cls):
        """Create the invoice unless this student already has one that includes this fee."""
        if (FeeInvoice.objects.filter(student=student, fee_item=item).exists()
                or FeeInvoiceItem.objects.filter(invoice__student=student, fee_item=item).exists()):
            return False
        amount = FeeService._amount(item, cls)
        invoice = FeeInvoice.objects.create(
            school=item.school, student=student, fee_item=item, amount_due=amount, status='unpaid')
        FeeInvoiceItem.objects.create(invoice=invoice, fee_item=item, amount_due=amount)
        return True

    @staticmethod
    @transaction.atomic
    def invoice_students_for_item(item):
        """Bill every active student the fee applies to. Returns how many invoices were made."""
        if not item.is_mandatory or not FeeService._is_current(item, item.school):
            return 0
        students = User.objects.filter(
            school=item.school, role='student', student_profile__student_status='active',
            student_profile__class_group__isnull=False,
        ).select_related('student_profile__class_group')
        made = 0
        for student in students:
            cls = student.student_profile.class_group
            if FeeService._applies(item, cls):
                made += int(FeeService._ensure_invoice(student, item, cls))
        return made

    @staticmethod
    @transaction.atomic
    def invoice_student(student):
        """Bill one student for every current mandatory fee that applies to their class."""
        sp = getattr(student, 'student_profile', None)
        cls = sp.class_group if sp else None
        if not (sp and cls and sp.student_status == 'active' and student.school_id):
            return 0
        made = 0
        for item in FeeItem.objects.filter(school_id=student.school_id, is_mandatory=True).select_related('school'):
            if FeeService._is_current(item, item.school) and FeeService._applies(item, cls):
                made += int(FeeService._ensure_invoice(student, item, cls))
        return made

    # -- Deleting a fee together with its bills ------------------

    @staticmethod
    def invoices_for_item(item):
        """Every invoice that bills this fee, either as the whole invoice or as one line of it."""
        return FeeInvoice.objects.filter(
            models.Q(fee_item=item) | models.Q(items__fee_item=item)).distinct()

    @staticmethod
    def delete_impact(item):
        """What deleting this fee would touch: how many invoices, and how many have payments."""
        invoices = list(FeeInvoice.objects.filter(
            models.Q(fee_item=item) | models.Q(items__fee_item=item)).distinct().prefetch_related('items'))
        paid = [
            i for i in invoices
            if i.amount_paid > 0 or any(line.amount_paid > 0 for line in i.items.all())
        ]
        return {'invoices': len(invoices), 'with_payments': len(paid)}

    @staticmethod
    @transaction.atomic
    def remove_invoices_for_item(item):
        """Remove this fee's bills. Refuses if any has a payment, so no money record is lost.

        An invoice that bills only this fee is deleted. An invoice that bundles other fees too
        keeps them: only this fee's line is removed and the invoice total is reduced.
        Returns the number of invoices deleted.
        """
        impact = FeeService.delete_impact(item)
        if impact['with_payments']:
            raise ValueError(
                f"{impact['with_payments']} invoice(s) for this fee already have a payment recorded, "
                'so they cannot be deleted.')
        deleted = 0
        for invoice in FeeService.invoices_for_item(item).prefetch_related('items'):
            lines = list(invoice.items.all())
            mine = [line for line in lines if line.fee_item_id == item.id]
            others = [line for line in lines if line.fee_item_id != item.id]
            if not others:
                invoice.delete()
                deleted += 1
                continue
            invoice.amount_due -= sum(line.amount_due for line in mine)
            invoice.save(update_fields=['amount_due'])
            for line in mine:
                line.delete()
        return deleted
