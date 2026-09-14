from rest_framework.exceptions import ValidationError
from django.shortcuts import get_object_or_404

from apps.accounts.models import User, StudentAccessCode
from apps.base.encryption import hash_value, verify_hash
from apps.fees.models import FeeInvoice, FeeInvoiceItem
from apps.exams.models import ReportCard
from apps.attendance.models import Attendance
from apps.comms.models import Notification


class PortalService:

    @staticmethod
    def lookup_student(code=None, admission_no=None):
        if code and not admission_no:
            code_hash = hash_value(code)
            sac = get_object_or_404(
                StudentAccessCode.objects.select_related(
                    'student', 'student__school', 'student__student_profile__class_group'
                ),
                code_hash=code_hash,
            )
            student = sac.student
        else:
            if not admission_no:
                raise ValidationError('Admission number is required.')
            if not code:
                raise ValidationError('Access code is required.')
            admission_hash = hash_value(admission_no)
            student = get_object_or_404(
                User.objects.select_related(
                    'school', 'student_profile__class_group'
                ),
                student_profile__admission_no_hash=admission_hash,
                role='student',
            )
            sac = get_object_or_404(StudentAccessCode, student=student)
            if not verify_hash(code, sac.code):
                raise ValidationError('Invalid access code.')

        sp = getattr(student, 'student_profile', None)

        invoices = FeeInvoice.objects.filter(student=student)
        total_due = sum(float(i.amount_due) for i in invoices)
        total_paid = sum(float(i.amount_paid) for i in invoices)

        invoice_ids = [i.id for i in invoices]
        if invoice_ids:
            invoice_items = FeeInvoiceItem.objects.filter(invoice_id__in=invoice_ids).select_related('fee_item')
            fee_breakdown = [
                {
                    'description': item.fee_item.name if item.fee_item else 'Fee item',
                    'amount_due': float(item.amount_due),
                    'amount_paid': float(item.amount_paid),
                }
                for item in invoice_items
            ]
        else:
            fee_breakdown = []

        if total_due == 0:
            fee_status = 'unpaid'
        elif total_paid >= total_due:
            fee_status = 'paid'
        elif total_paid > 0:
            fee_status = 'partial'
        else:
            fee_status = 'unpaid'

        latest_rc = ReportCard.objects.filter(student=student).order_by('-generated_at').first()
        report_card_data = None
        if latest_rc:
            grades = latest_rc.grades
            subjects = []
            if isinstance(grades, list):
                for entry in grades:
                    if isinstance(entry, dict):
                        subjects.append({
                            'name': entry.get('subject', entry.get('name', 'Subject')),
                            'score': entry.get('score', entry.get('total', 0)),
                            'grade': entry.get('grade', ''),
                        })
                    elif isinstance(entry, str):
                        subjects.append({'name': entry, 'score': 0, 'grade': ''})
            elif isinstance(grades, dict):
                for key, val in grades.items():
                    if isinstance(val, dict):
                        subjects.append({
                            'name': val.get('subject', val.get('name', key)),
                            'score': val.get('score', val.get('total', 0)),
                            'grade': val.get('grade', ''),
                        })
                    else:
                        subjects.append({'name': key, 'score': float(val) if val else 0, 'grade': ''})

            report_card_data = {
                'term': latest_rc.term,
                'academic_year': latest_rc.academic_year,
                'average': float(latest_rc.average) if latest_rc.average else None,
                'class_rank': latest_rc.class_rank,
                'subjects': subjects,
            }

        attendance_records = Attendance.objects.filter(student=student)
        total_att = attendance_records.count()
        present_count = attendance_records.filter(status='present').count()
        absent_count = attendance_records.filter(status='absent').count()
        late_count = attendance_records.filter(status='late').count()
        attendance_rate = round(present_count / total_att * 100, 1) if total_att > 0 else None

        notifs = Notification.objects.filter(recipient=student)[:5]
        recent_notifs = [{
            'id': str(n.id),
            'type': n.notif_type,
            'title': n.title,
            'message': n.message,
            'read': n.read,
            'created_at': n.created_at.isoformat(),
        } for n in notifs]

        return {
            'student_id': str(student.id),
            'full_name': student.get_full_name(),
            'admission_no': sp.admission_no if sp else None,
            'class_name': sp.class_group.name if sp and sp.class_group else None,
            'status': sp.student_status if sp else None,
            'school_name': student.school.name if student.school else None,
            'recent_notifications': recent_notifs,
            'fee_summary': {
                'total_due': total_due,
                'total_paid': total_paid,
                'balance': total_due - total_paid,
                'status': fee_status,
                'items': fee_breakdown,
            },
            'latest_report_card': report_card_data,
            'attendance': {
                'rate': attendance_rate,
                'present': present_count,
                'absent': absent_count,
                'late': late_count,
                'total': total_att,
            },
        }
