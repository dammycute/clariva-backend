from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.response import Response
from django.core.cache import cache
from django.conf import settings

from apps.accounts.models import User, StudentAccessCode
from apps.base.encryption import hash_value, verify_hash
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


def _generate_otp(phone):
    import secrets
    otp = ''.join(secrets.choice('0123456789') for _ in range(6))
    cache.set(f'portal_otp:{phone}', otp, 300)  # 5 min expiry
    return otp


def _verify_otp(phone, otp):
    stored = cache.get(f'portal_otp:{phone}')
    if not stored or stored != otp:
        return False
    cache.delete(f'portal_otp:{phone}')
    return True


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@_rate_limit_ip('portal_lookup')
def portal_lookup(request):
    admission_no = request.data.get('admission_no', '').strip()
    code = request.data.get('code', '').strip().upper()
    school_id = request.data.get('school_id')
    subdomain = request.data.get('subdomain', '').strip()

    if not school_id and not subdomain:
        return Response(
            {'error': 'school_id or subdomain is required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    from apps.schools.models import School
    if subdomain:
        try:
            school = School.objects.get(subdomain__iexact=subdomain)
            school_id = school.id
        except School.DoesNotExist:
            return Response({'error': 'School not found'}, status=status.HTTP_404_NOT_FOUND)

    if code and not admission_no:
        code_hash = hash_value(code)
        try:
            sac = StudentAccessCode.objects.select_related(
                'student', 'student__school', 'student__student_profile__class_group'
            ).get(code_hash=code_hash, student__school_id=school_id)
        except StudentAccessCode.DoesNotExist:
            return Response({'error': 'Invalid access code'}, status=status.HTTP_404_NOT_FOUND)
        student = sac.student
    else:
        if not admission_no:
            return Response({'error': 'Admission number is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not code:
            return Response({'error': 'Access code is required'}, status=status.HTTP_400_BAD_REQUEST)

        admission_hash = hash_value(admission_no)
        try:
            student = User.objects.select_related(
                'school', 'student_profile__class_group'
            ).get(
                student_profile__admission_no_hash=admission_hash,
                role='student',
                school_id=school_id
            )
        except User.DoesNotExist:
            return Response({'error': 'Student not found with this admission number'}, status=status.HTTP_404_NOT_FOUND)

        try:
            sac = StudentAccessCode.objects.get(student=student)
        except StudentAccessCode.DoesNotExist:
            return Response({'error': 'No access code set for this student'}, status=status.HTTP_404_NOT_FOUND)

        if not verify_hash(code, sac.code):
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

    sp = getattr(student, 'student_profile', None)
    return Response({
        'student_id': student.id,
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
    })


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@_rate_limit_ip('portal_setup_init')
def portal_setup_initiate(request):
    phone = request.data.get('phone', '').strip()
    student_code = request.data.get('student_code', '').strip().upper()
    subdomain = request.data.get('subdomain', '').strip()

    if not phone or not student_code:
        return Response(
            {'error': 'phone and student_code are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Rate limit per phone: 5 attempts per 15 minutes
    phone_key = f'portal_setup_attempts:{phone}'
    attempts = cache.get(phone_key, 0)
    if attempts >= 5:
        return Response(
            {'error': 'Too many attempts. Try again in 15 minutes.'},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    # Validate student_code belongs to a real student
    sac_qs = StudentAccessCode.objects.select_related('student', 'student__school')
    if subdomain:
        sac_qs = sac_qs.filter(student__school__subdomain__iexact=subdomain)

    student_code_hash = hash_value(student_code)
    try:
        sac = sac_qs.get(code_hash=student_code_hash)
    except StudentAccessCode.DoesNotExist:
        return Response({'error': 'Invalid student code'}, status=status.HTTP_404_NOT_FOUND)

    otp = _generate_otp(phone)
    cache.set(phone_key, attempts + 1, 900)  # 15 min window

    # In production, send OTP via Termii/SMS here
    # For dev, return OTP in response for testing
    response_data = {'message': 'OTP sent to your phone number'}
    if settings.DEBUG:
        response_data['otp'] = otp  # Remove in production
    return Response(response_data)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
@_rate_limit_ip('portal_setup_verify')
def portal_setup_verify(request):
    phone = request.data.get('phone', '').strip()
    password = request.data.get('password', '')
    student_code = request.data.get('student_code', '').strip().upper()
    otp = request.data.get('otp', '').strip()
    subdomain = request.data.get('subdomain', '').strip()

    if not phone or not password or not student_code or not otp:
        return Response(
            {'error': 'phone, password, student_code, and otp are required'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if len(password) < 6:
        return Response(
            {'error': 'Password must be at least 6 characters'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not _verify_otp(phone, otp):
        return Response(
            {'error': 'Invalid or expired OTP'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    sac_qs = StudentAccessCode.objects.select_related('student', 'student__school')
    if subdomain:
        sac_qs = sac_qs.filter(student__school__subdomain__iexact=subdomain)

    student_code_hash = hash_value(student_code)
    try:
        sac = sac_qs.get(code_hash=student_code_hash)
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

    if not created:
        # Existing account — verify phone ownership before allowing password reset
        if parent.phone != phone:
            return Response(
                {'error': 'Phone number does not match existing account'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    parent.set_password(password)
    parent.save()

    GuardianStudent.objects.get_or_create(guardian=parent, student=student)

    # Clear rate limit on success
    cache.delete(f'portal_setup_attempts:{phone}')

    return Response({'message': 'Account set up successfully. You can now log in.'}, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([permissions.AllowAny])
def portal_setup(request):
    return Response(
        {'error': 'Use POST /api/portal/setup/initiate/ then POST /api/portal/setup/verify/ with OTP'},
        status=status.HTTP_400_BAD_REQUEST,
    )


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def portal_children(request):
    user = request.user
    if user.role != 'parent':
        return Response({'error': 'Not a parent account'}, status=status.HTTP_403_FORBIDDEN)

    links = GuardianStudent.objects.filter(guardian=user).select_related(
        'student', 'student__student_profile__class_group'
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

        sp = getattr(student, 'student_profile', None)
        result.append({
            'id': student.id,
            'full_name': student.get_full_name(),
            'admission_no': sp.admission_no if sp else None,
            'class_name': sp.class_group.name if sp and sp.class_group else None,
            'status': sp.student_status if sp else None,
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
