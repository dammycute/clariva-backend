from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db.models import Sum, Count, Q
from ..fees.models import FeeInvoice, FeeItem
from apps.accounts.models import User


FINANCE_ROLES = {'school_admin', 'bursary', 'super_admin'}


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def bursary_summary(request):
    if getattr(request.user, 'role', None) not in FINANCE_ROLES:
        return Response({'error': 'Access denied'}, status=403)

    school_id = request.user.school_id
    if not school_id:
        return Response({'error': 'No school assigned'}, status=400)

    invoices = FeeInvoice.objects.filter(student__school_id=school_id)
    students = User.objects.filter(school_id=school_id, role='student', student_status='active')

    total_due = invoices.aggregate(d=Sum('amount_due'))['d'] or 0
    total_paid = invoices.aggregate(p=Sum('amount_paid'))['p'] or 0
    outstanding = total_due - total_paid

    paid_invoices = invoices.filter(status='paid').count()
    pending_invoices = invoices.filter(~Q(status='paid')).count()

    fee_items = FeeItem.objects.filter(school_id=school_id)
    item_breakdown = []
    for item in fee_items:
        item_invoices = invoices.filter(fee_item=item)
        item_due = item_invoices.aggregate(d=Sum('amount_due'))['d'] or 0
        item_paid = item_invoices.aggregate(p=Sum('amount_paid'))['p'] or 0
        item_breakdown.append({
            'name': item.name,
            'total_due': float(item_due),
            'total_paid': float(item_paid),
            'outstanding': float(item_due - item_paid),
        })

    return Response({
        'total_students': students.count(),
        'total_due': float(total_due),
        'total_paid': float(total_paid),
        'outstanding': float(outstanding),
        'collection_rate': round(float(total_paid / total_due * 100), 1) if total_due > 0 else 0,
        'paid_invoices': paid_invoices,
        'pending_invoices': pending_invoices,
        'item_breakdown': item_breakdown,
    })
