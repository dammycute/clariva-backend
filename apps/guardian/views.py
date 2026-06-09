from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.core.cache import cache

from apps.accounts.models import User, StudentAccessCode
from .models import GuardianStudent


def _rate_limit_ip(key_prefix, max_requests=10, window=60):
    def decorator(view_fn):
        def wrapper(request, *args, **kwargs):
            ip = request.META.get('REMOTE_ADDR', 'unknown')
            cache_key = f'{key_prefix}:{ip}'
            count = cache.get(cache_key, 0)
            if count >= max_requests:
                return Response(
                    {'error': 'Too many requests. Try again later.'},
                    status=status.HTTP_429_TOO_MANY_REQUESTS,
                )
            cache.set(cache_key, count + 1, window)
            return view_fn(request, *args, **kwargs)
        return wrapper
    return decorator


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@_rate_limit_ip('portal_lookup')
def portal_lookup(request):
    admission_no = request.data.get('admission_no', '').strip()
    code = request.data.get('code', '').strip().upper()

    if code and not admission_no:
        try:
            sac = StudentAccessCode.objects.select_related(
                'student', 'student__school', 'student__class_group'
            ).get(code=code)
        except StudentAccessCode.DoesNotExist:
            return Response({'error': 'Invalid access code'}, status=status.HTTP_404_NOT_FOUND)
        student = sac.student
    else:
        if not admission_no:
            return Response({'error': 'Admission number is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not code:
            return Response({'error': 'Access code is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            student = User.objects.select_related(
                'school', 'class_group'
            ).get(admission_no__iexact=admission_no, role='student')
        except User.DoesNotExist:
            return Response({'error': 'Student not found with this admission number'}, status=status.HTTP_404_NOT_FOUND)

        try:
            sac = StudentAccessCode.objects.get(student=student)
        except StudentAccessCode.DoesNotExist:
            return Response({'error': 'No access code set for this student'}, status=status.HTTP_404_NOT_FOUND)

        if sac.code != code:
            return Response({'error': 'Invalid access code'}, status=status.HTTP_401_UNAUTHORIZED)

    from apps.fees.models import FeeInvoice, FeeInvoiceItem
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

    from apps.exams.models import ReportCard
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

    from apps.attendance.models import Attendance
    attendance_records = Attendance.objects.filter(student=student)
    total_att = attendance_records.count()
    present_count = attendance_records.filter(status='present').count()
    absent_count = attendance_records.filter(status='absent').count()
    late_count = attendance_records.filter(status='late').count()
    attendance_rate = round(present_count / total_att * 100, 1) if total_att > 0 else None

    from apps.comms.models import Notification
    recent_notifs = []
    notifs = Notification.objects.filter(recipient=student)[:5]
    recent_notifs = [{
        'id': str(n.id),
        'type': n.notif_type,
        'title': n.title,
        'message': n.message,
        'read': n.read,
        'created_at': n.created_at.isoformat(),
    } for n in notifs]

    return Response({
        'student_id': student.id,
        'full_name': student.get_full_name(),
        'admission_no': student.admission_no,
        'class_name': student.class_group.name if student.class_group else None,
        'status': student.student_status,
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
    })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def portal_setup(request):
    phone = request.data.get('phone', '').strip()
    password = request.data.get('password', '')
    student_code = request.data.get('student_code', '').strip().upper()

    if not phone or not password or not student_code:
        return Response({'error': 'phone, password, and student_code are required'}, status=status.HTTP_400_BAD_REQUEST)

    if len(password) < 6:
        return Response({'error': 'Password must be at least 6 characters'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        sac = StudentAccessCode.objects.select_related('student', 'student__school').get(code=student_code)
    except StudentAccessCode.DoesNotExist:
        return Response({'error': 'Invalid student code'}, status=status.HTTP_404_NOT_FOUND)

    student = sac.student
    school = student.school

    parent_username = f'parent.{phone}'
    parent, created = User.objects.get_or_create(
        username=parent_username,
        defaults={
            'school': school,
            'phone': phone,
            'role': 'parent',
            'email': f'{parent_username}@parent.clariva.ng',
        },
    )
    if created:
        parent.set_password(password)
        parent.save()
    else:
        parent.set_password(password)
        parent.save()

    GuardianStudent.objects.get_or_create(guardian=parent, student=student)

    return Response({'message': 'Account set up successfully. You can now log in.'}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def portal_children(request):
    user = request.user
    if user.role != 'parent':
        return Response({'error': 'Not a parent account'}, status=status.HTTP_403_FORBIDDEN)

    links = GuardianStudent.objects.filter(guardian=user).select_related(
        'student', 'student__class_group'
    )

    from apps.fees.models import FeeInvoice
    from apps.exams.models import ReportCard
    from apps.attendance.models import Attendance

    result = []
    for link in links:
        student = link.student
        invoices = FeeInvoice.objects.filter(student=student)
        total_due = sum(float(i.amount_due) for i in invoices)
        total_paid = sum(float(i.amount_paid) for i in invoices)

        latest_rc = ReportCard.objects.filter(student=student).order_by('-generated_at').first()

        total_attendance = Attendance.objects.filter(student=student).count()
        present_count = Attendance.objects.filter(student=student, status='present').count()
        attendance_rate = round(present_count / total_attendance * 100, 1) if total_attendance > 0 else None

        from apps.comms.models import Notification
        recent_notifs = []
        notifs = Notification.objects.filter(recipient=student)[:5]
        recent_notifs = [{
            'id': str(n.id),
            'type': n.notif_type,
            'title': n.title,
            'message': n.message,
            'read': n.read,
            'created_at': n.created_at.isoformat(),
        } for n in notifs]

        result.append({
            'id': student.id,
            'full_name': student.get_full_name(),
            'admission_no': student.admission_no,
            'class_name': student.class_group.name if student.class_group else None,
            'status': student.student_status,
            'gender': student.gender,
            'recent_notifications': recent_notifs,
            'fee_summary': {
                'total_due': total_due,
                'total_paid': total_paid,
                'balance': total_due - total_paid,
            },
            'latest_report_card': {
                'term': latest_rc.term if latest_rc else None,
                'academic_year': latest_rc.academic_year if latest_rc else None,
                'average': float(latest_rc.average) if latest_rc and latest_rc.average else None,
            } if latest_rc else None,
            'attendance_rate': attendance_rate,
        })

    return Response(result)
