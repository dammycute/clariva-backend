from django.db.models import Sum, Count, Q, Avg
from apps.students.models import Student
from apps.staff.models import Staff
from apps.classes.models import Class
from apps.exams.models import Subject, ExamSession
from apps.fees.models import FeeInvoice
from apps.attendance.models import Attendance


def get_summary(school_id):
    students = Student.objects.filter(school_id=school_id)
    active_students = students.filter(status='active')
    staff = Staff.objects.filter(school_id=school_id)
    classes = Class.objects.filter(school_id=school_id)
    subjects = Subject.objects.filter(school_id=school_id)
    invoices = FeeInvoice.objects.filter(student__school_id=school_id)
    attendance = Attendance.objects.filter(student__school_id=school_id)

    total_invoices = invoices.aggregate(
        due=Sum('amount_due'), paid=Sum('amount_paid')
    )
    total_att = attendance.count()
    present_att = attendance.filter(status='present').count()

    exam_sessions = ExamSession.objects.filter(school_id=school_id)
    submitted = exam_sessions.filter(status='submitted')
    avg_score = submitted.aggregate(Avg('score'))['score__avg']

    return {
        'students': active_students.count(),
        'total_students': students.count(),
        'staff': staff.count(),
        'classes': classes.count(),
        'subjects': subjects.count(),
        'fees': {
            'total_due': float(total_invoices['due'] or 0),
            'total_paid': float(total_invoices['paid'] or 0),
            'outstanding': float((total_invoices['due'] or 0) - (total_invoices['paid'] or 0)),
        },
        'attendance': {
            'total': total_att,
            'present': present_att,
            'rate': round(present_att / total_att * 100, 1) if total_att > 0 else 0,
        },
        'exams': {
            'total_sessions': exam_sessions.count(),
            'submitted': submitted.count(),
            'avg_score': round(float(avg_score), 2) if avg_score else 0,
        },
    }
