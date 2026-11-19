from decimal import Decimal

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
            return Decimal(str(item.pricing_tiers[year_group]))
        return Decimal(str(item.amount))

    @staticmethod
    def _same_period(a, b):
        """Do two fee items belong to the same term and year? A blank term or year fits any."""
        return ((not a.term or not b.term or a.term == b.term)
                and (not a.academic_year or not b.academic_year or a.academic_year == b.academic_year))

    @staticmethod
    def _bill(pairs):
        """Bill each (student, fee item, class). Fees add up on ONE invoice per student.

        A student's fees for a term live on a single invoice, one line per fee, and the invoice
        total is their sum. A new fee is added as a line on the student's newest unpaid or part-paid
        invoice for that term. A fully paid invoice is a closed receipt, so it is left alone and a
        new invoice is started. A student already billed for the fee is skipped, so this is safe to
        repeat. It runs in a handful of queries however many students there are.
        Returns how many fee lines were added.
        """
        if not pairs:
            return 0
        student_ids = {s.id for s, _, _ in pairs}
        item_ids = {i.id for _, i, _ in pairs}

        billed = set(FeeInvoice.objects.filter(student_id__in=student_ids, fee_item_id__in=item_ids)
                     .values_list('student_id', 'fee_item_id'))
        billed |= set(FeeInvoiceItem.objects.filter(invoice__student_id__in=student_ids, fee_item_id__in=item_ids)
                      .values_list('invoice__student_id', 'fee_item_id'))

        open_invoices = {}
        for inv in (FeeInvoice.objects.filter(student_id__in=student_ids).exclude(status='paid')
                    .order_by('-created_at').prefetch_related('items__fee_item')):
            open_invoices.setdefault(inv.student_id, []).append(inv)

        new_invoices, lines, grown = {}, [], {}
        for student, item, cls in pairs:
            if (student.id, item.id) in billed:
                continue
            amount = FeeService._amount(item, cls)
            invoice = new_invoices.get(student.id)
            if invoice is None:
                invoice = next((
                    inv for inv in open_invoices.get(student.id, [])
                    if all(FeeService._same_period(line.fee_item, item)
                           for line in inv.items.all() if line.fee_item_id)), None)
                if invoice is not None:
                    grown[invoice.id] = invoice
                else:
                    invoice = FeeInvoice(school=item.school, student=student, fee_item=item,
                                         amount_due=0, status='unpaid')
                    new_invoices[student.id] = invoice
            invoice.amount_due += amount
            lines.append(FeeInvoiceItem(invoice=invoice, fee_item=item, amount_due=amount))
            billed.add((student.id, item.id))

        FeeInvoice.objects.bulk_create(list(new_invoices.values()))
        if grown:
            FeeInvoice.objects.bulk_update(list(grown.values()), ['amount_due'])
        FeeInvoiceItem.objects.bulk_create(lines)
        return len(lines)

    @staticmethod
    @transaction.atomic
    def invoice_students_for_item(item):
        """Bill every active student this fee applies to. Returns how many were billed."""
        if not item.is_mandatory or not FeeService._is_current(item, item.school):
            return 0
        students = User.objects.filter(
            school=item.school, role='student', student_profile__student_status='active',
            student_profile__class_group__isnull=False,
        ).select_related('student_profile__class_group')
        pairs = [(s, item, s.student_profile.class_group) for s in students
                 if FeeService._applies(item, s.student_profile.class_group)]
        return FeeService._bill(pairs)

    @staticmethod
    @transaction.atomic
    def invoice_student(student):
        """Bill one student for every current mandatory fee that applies to their class."""
        sp = getattr(student, 'student_profile', None)
        cls = sp.class_group if sp else None
        if not (sp and cls and sp.student_status == 'active' and student.school_id):
            return 0
        pairs = [(student, item, cls)
                 for item in FeeItem.objects.filter(school_id=student.school_id, is_mandatory=True).select_related('school')
                 if FeeService._is_current(item, item.school) and FeeService._applies(item, cls)]
        return FeeService._bill(pairs)

    @staticmethod
    @transaction.atomic
    def merge_open_invoices(school, apply=False):
        """Join a student's separate unpaid invoices for the same term into one.

        For fixing invoices made before fees were combined. Only invoices with no payment at all
        are touched. Returns {'students', 'invoices_removed'}. With apply=False nothing is changed.
        """
        by_student = {}
        for inv in (FeeInvoice.objects.filter(school=school, amount_paid=0)
                    .exclude(status='paid').order_by('created_at').prefetch_related('items__fee_item')):
            if any(line.amount_paid > 0 for line in inv.items.all()):
                continue
            by_student.setdefault(inv.student_id, []).append(inv)

        students = removed = 0
        for invoices in by_student.values():
            groups = []                       # invoices that share a term and year
            for inv in invoices:
                for group in groups:
                    if all(FeeService._same_period(a.fee_item, b.fee_item)
                           for a in group[0].items.all() for b in inv.items.all()
                           if a.fee_item_id and b.fee_item_id):
                        group.append(inv)
                        break
                else:
                    groups.append([inv])
            merged_any = False
            for group in groups:
                if len(group) < 2:
                    continue
                keep, rest = group[0], group[1:]
                merged_any = True
                removed += len(rest)
                if not apply:
                    continue
                for inv in rest:
                    FeeInvoiceItem.objects.filter(invoice=inv).update(invoice=keep)
                    keep.amount_due += inv.amount_due
                    inv.delete()
                keep.save(update_fields=['amount_due'])
            students += int(merged_any)
        return {'students': students, 'invoices_removed': removed}

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
