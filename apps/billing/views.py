import hmac
import json
import logging
import re
import uuid
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.locations.models import State
from apps.permissions import ADMIN_ROLES
from apps.schools.models import School
from apps.schools.views import IsSuperAdmin
from . import paystack, term_dates
from .exceptions import PaymentProblem
from .models import Payment, TermCalendar
from .serializers import ManualPaymentSerializer, PaymentSerializer, TermCalendarSerializer
from .services import (
    PAYMENT_WINDOW_DAYS, apply_manual_payment, billing_state, blocks_for, capacity,
    create_payment, current_term_paid, fulfil_payment, invalidate, limit_for_blocks,
    price_for_blocks, quote_students, school_billing, status_payload, term_to_pay,
    term_window,
)

logger = logging.getLogger('apps')


def school_for(request):
    """The school this request is about. Super admins name one with ?school=."""
    if getattr(request.user, 'role', None) == 'super_admin':
        school_id = request.query_params.get('school') or request.data.get('school')
        if not school_id:
            raise PaymentProblem('Pass ?school=<id>.', code='school_required')
        return get_object_or_404(School, pk=school_id)
    school = getattr(request.user, 'school', None)
    if school is None:
        raise PaymentProblem('No school is assigned to your account.', code='no_school')
    return school


def safe_callback(url):
    """Where Paystack may send the payer back. Only our own websites; anything else gets the default."""
    default = getattr(settings, 'PAYSTACK_CALLBACK_URL', '')
    if not url:
        return default
    parts = urlsplit(str(url))
    origin = f'{parts.scheme}://{parts.netloc}'
    ours = origin in getattr(settings, 'CORS_ALLOWED_ORIGINS', []) or any(
        re.match(pattern, origin) for pattern in getattr(settings, 'CORS_ALLOWED_ORIGIN_REGEXES', []))
    return str(url) if ours else default


def is_admin(user):
    return getattr(user, 'role', None) in ADMIN_ROLES


class BillingStatusView(APIView):
    """What this school owes, what it has, and what it can do today."""

    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        return Response(status_payload(school_for(request)))


class PaymentListView(generics.ListAPIView):
    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def get_queryset(self):
        if not is_admin(self.request.user):
            raise PermissionDenied('Only school admins can see the payment history.')
        school = school_for(self.request)
        return Payment.objects.filter(school=school).select_related('school')


class InitializePaymentView(APIView):
    """Start a payment. The amount is worked out here, never taken from the browser."""

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        if not is_admin(request.user):
            raise PermissionDenied('Only school admins can pay for a school.')
        school = request.user.school
        if school is None:
            raise PaymentProblem('No school is assigned to your account.', code='no_school')

        today = timezone.localdate()
        info = school_billing(school.pk)
        if info.get('status') == 'suspended':
            raise PaymentProblem('This school account is suspended. Contact support.', code='suspended')
        state = billing_state(info.get('access_until'), today)

        kind = (request.data.get('kind') or 'renewal').lower()
        students = request.data.get('students')

        # An upgrade only makes sense while the school still has access; otherwise it is a renewal.
        if kind == 'upgrade' and state in ('active', 'grace') and school.access_until:
            if students in (None, ''):
                raise PaymentProblem('Say how many students you need.', code='students_required')
            try:
                students = int(students)
            except (TypeError, ValueError):
                raise PaymentProblem('Say how many students you need.', code='students_required')
            blocks = blocks_for(students)
            if blocks <= school.paid_blocks:
                raise PaymentProblem(
                    f'Your plan already covers {limit_for_blocks(school.paid_blocks)} students.',
                    code='no_upgrade_needed',
                )
            amount = price_for_blocks(blocks - school.paid_blocks) * 100
            academic_year, term = current_term_paid(school)      # places for this term, not the next
            # An upgrade keeps the dates it already has.
            covers_from, access_until = today, school.access_until
        else:
            kind = 'renewal' if kind == 'upgrade' else (kind if kind in ('new', 'renewal') else 'renewal')
            students = quote_students(school)
            if not students:
                raise PaymentProblem(
                    'Add your students first, so we know what to bill for.',
                    code='no_students',
                )
            academic_year, term = term_to_pay(school)
            window = term_window(school.state, school, academic_year, term)
            if window is None:
                raise PaymentProblem(
                    "Your state's term dates are not published yet. We will contact you.",
                    code='missing_calendar',
                )
            opens_on = window['resumes_on'] - timedelta(days=PAYMENT_WINDOW_DAYS)
            if today < opens_on and state not in ('grace', 'lapsed'):
                raise PaymentProblem(
                    f'Payment for {term} opens on {opens_on:%d %b %Y}.',
                    code='window_closed',
                )
            blocks = blocks_for(students)
            amount = price_for_blocks(blocks) * 100
            covers_from = max(window['resumes_on'], today)
            access_until = window['access_until']

        payment = create_payment(
            school=school, kind=kind, students=students, academic_year=academic_year,
            term=term, amount=amount, blocks_after=blocks, covers_from=covers_from,
            access_until=access_until, created_by=request.user,
        )

        callback = safe_callback(request.data.get('callback_url'))
        email = request.user.email
        try:
            data = paystack.initialize(
                email=email, amount_kobo=amount, reference=payment.reference,
                callback_url=callback,
                metadata={'school_id': str(school.pk), 'payment_id': str(payment.pk), 'kind': kind},
            )
        except paystack.PaystackError as exc:
            Payment.objects.filter(pk=payment.pk).update(status='failed')
            raise PaymentProblem(str(exc), code='paystack_unavailable', status_code=502)

        return Response({
            'reference': payment.reference,
            'authorization_url': data.get('authorization_url'),
            'access_code': data.get('access_code'),
            'amount': amount,
            'blocks': blocks,
            'students': students,
            'kind': kind,
            'term': term,
            'academic_year': academic_year,
            'covers_from': covers_from,
            'access_until': access_until,
        }, status=status.HTTP_201_CREATED)


class VerifyPaymentView(APIView):
    """After the browser comes back from Paystack: verify, then write."""

    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        if not is_admin(request.user):
            raise PermissionDenied('Only school admins can confirm a payment.')
        reference = (request.data.get('reference') or '').strip()
        if not reference:
            raise PaymentProblem('A reference is required.', code='reference_required')
        school = request.user.school
        payment = Payment.objects.filter(school=school, reference=reference).first()
        if payment is None:
            raise PaymentProblem('No payment with that reference.', code='unknown_reference',
                                 status_code=404)
        if payment.status == 'paid':
            return Response({'status': 'paid', 'duplicate': True,
                             'payment': PaymentSerializer(payment).data})
        try:
            payload = paystack.verify(reference)
        except paystack.PaystackError as exc:
            raise PaymentProblem(str(exc), code='paystack_unavailable', status_code=502)
        paid = fulfil_payment(payment, payload)
        return Response({'status': paid.status, 'duplicate': False,
                         'payment': PaymentSerializer(paid).data})


class PaystackWebhookView(APIView):
    """Paystack calls this. No auth header, no throttle: the signature is the auth."""

    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = ()

    def post(self, request):
        raw = request.body
        if not paystack.signature_ok(raw, request.META):
            return Response({'detail': 'Invalid signature.', 'code': 'bad_signature'},
                            status=status.HTTP_401_UNAUTHORIZED)
        try:
            event = json.loads(raw.decode() or '{}')
        except (ValueError, UnicodeDecodeError):
            return Response({'detail': 'Invalid body.'}, status=status.HTTP_400_BAD_REQUEST)

        if event.get('event') not in ('charge.success',):
            return Response({'status': 'ignored'})

        data = event.get('data') or {}
        reference = data.get('reference')
        payment = Payment.objects.filter(reference=reference).first() if reference else None
        if payment is None:
            return Response({'status': 'unknown reference'})

        # No event id exists, and a resend is not marked as one: dedupe on the reference.
        if payment.status == 'paid':
            return Response({'status': 'ok', 'duplicate': True})

        try:
            payload = paystack.verify(reference)     # the webhook only triggers; verify decides
            fulfil_payment(payment, payload)
        except paystack.PaystackError:
            # Let Paystack retry later.
            return Response({'detail': 'Could not verify yet.'}, status=status.HTTP_502_BAD_GATEWAY)
        except PaymentProblem as exc:
            logger.warning('Webhook could not settle %s: %s', reference, exc.detail)
            return Response({'detail': 'Not settled.', 'code': 'not_settled'},
                            status=status.HTTP_409_CONFLICT)
        return Response({'status': 'ok'})


class TermCalendarViewSet(viewsets.ModelViewSet):
    """State term dates, and per-school overrides. Super admin only."""

    queryset = TermCalendar.objects.select_related('state', 'school').all()
    serializer_class = TermCalendarSerializer
    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def get_queryset(self):
        qs = super().get_queryset()
        state_id = self.request.query_params.get('state')
        year = self.request.query_params.get('academic_year')
        school = self.request.query_params.get('school')
        if state_id:
            qs = qs.filter(state_id=state_id)
        if year:
            qs = qs.filter(academic_year=year)
        if school:
            qs = qs.filter(school_id=school)
        return qs

    def perform_create(self, serializer):
        self._save(serializer)

    def perform_update(self, serializer):
        self._save(serializer)

    def _save(self, serializer):
        with transaction.atomic():
            row, _ = self._apply(serializer)
            term_dates.check_order([row], self.request.data.get('confirm_unusual') is True)

    def _apply(self, serializer):
        """Save one date: note who confirmed it, and lengthen payments made on an earlier estimate."""
        before = serializer.instance
        old_date = before.resumes_on if before else None
        was_estimate = bool(before and before.provisional)
        row = serializer.save()
        changed = old_date != row.resumes_on or was_estimate != row.provisional
        if not row.provisional and (changed or row.confirmed_at is None):
            row.confirmed_by, row.confirmed_at = self.request.user, timezone.now()
            row.save(update_fields=['confirmed_by', 'confirmed_at'])
        extended = term_dates.extend_paid_on_estimate(row, old_date) if was_estimate else 0
        return row, extended

    @action(detail=False, methods=['post'])
    def bulk(self, request):
        """Enter a session's dates once and apply them to several states. All or nothing."""
        states = request.data.get('states') or []
        dates = [d for d in (request.data.get('dates') or []) if isinstance(d, dict) and d.get('resumes_on')]
        if not isinstance(states, list) or not states or not dates:
            raise PaymentProblem('Choose at least one state and enter at least one date.', code='nothing_to_save')
        saved, extended = [], 0
        with transaction.atomic():
            for state in states:
                for entry in dates:
                    existing = TermCalendar.objects.filter(
                        state_id=self._uuid(state), school__isnull=True,
                        academic_year=entry.get('academic_year'), term=entry.get('term')).first()
                    data = {key: entry.get(key) for key in ('academic_year', 'term', 'resumes_on')}
                    data.update(state=state, school=None, provisional=entry.get('provisional') is True,
                                source_url=entry.get('source_url') or (existing.source_url if existing else ''))
                    serializer = self.get_serializer(existing, data=data, partial=existing is not None)
                    serializer.is_valid(raise_exception=True)
                    row, gained = self._apply(serializer)
                    saved.append(row)
                    extended += gained
            # checked after everything is saved, so several dates can move together
            term_dates.check_order(saved, request.data.get('confirm_unusual') is True)
        return Response({'saved': len(saved), 'extended_schools': extended})

    @staticmethod
    def _uuid(value):
        try:
            return uuid.UUID(str(value))
        except ValueError:
            raise PaymentProblem('Unknown state.', code='bad_state')

    @action(detail=False, methods=['get'])
    def due(self, request):
        """What the admins still have to enter, for states that have schools."""
        states, unmatched = term_dates.states_needing_dates()
        slots = lambda items: [{'academic_year': y, 'term': t} for y, t in items]
        return Response({
            'states': [{'id': str(s['state'].pk), 'name': s['state'].name, 'schools': s['schools'],
                        'missing': slots(s['missing']), 'unconfirmed': slots(s['unconfirmed'])}
                       for s in states],
            'schools_without_state': unmatched,
            'email_ready': bool(getattr(settings, 'RESEND_API_KEY', '')),
        })

    @action(detail=False, methods=['get', 'put'])
    def recipients(self, request):
        """Which platform admins are emailed about term dates. New admins are included."""
        if request.method == 'PUT':
            ids = {str(i) for i in (request.data.get('ids') or [])}
            chosen = [a.pk for a in term_dates.admins() if str(a.pk) in ids]
            if not chosen:
                raise PaymentProblem('Choose at least one admin, or nobody would be told.', code='nobody')
            for admin in term_dates.admins():
                wanted = admin.pk in chosen
                if admin.receives_calendar_reminders != wanted:
                    admin.receives_calendar_reminders = wanted
                    admin.save(update_fields=['receives_calendar_reminders'])
        return Response([{'id': str(a.pk), 'name': a.get_full_name() or a.email, 'email': a.email,
                          'selected': a.receives_calendar_reminders} for a in term_dates.admins()])


class AdminPaymentListView(generics.ListAPIView):
    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def get_queryset(self):
        qs = Payment.objects.select_related('school').all()
        school = self.request.query_params.get('school')
        status_filter = self.request.query_params.get('status')
        if school:
            qs = qs.filter(school_id=school)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class AdminSchoolBillingView(APIView):
    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def get(self, request, pk):
        return Response(status_payload(get_object_or_404(School, pk=pk)))


class ManualPaymentView(APIView):
    """A grant, an extension or a bank transfer, entered by the super admin and logged."""

    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def post(self, request):
        serializer = ManualPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        school = data['school']
        today = timezone.localdate()

        if data.get('access_until'):
            # Extend access to a date without buying a term.
            access_until = data['access_until']
            covers_from = today
            blocks = school.paid_blocks
            if not blocks:
                # With no places on record the school would have no student limit at all.
                students = data.get('students') or quote_students(school)
                if not students:
                    raise PaymentProblem('Say how many students this covers.', code='students_required')
                blocks = blocks_for(students)
            amount = 0
            academic_year, term = school.current_academic_year, school.current_term
            kind = 'grant'
        else:
            academic_year = data.get('academic_year') or school.current_academic_year
            term = data.get('term') or school.current_term
            window = term_window(school.state, school, academic_year, term)
            if window is None:
                raise PaymentProblem(
                    'The term dates for this state are missing. Enter them under Term calendars first.',
                    code='missing_calendar',
                )
            students = data.get('students') or quote_students(school)
            if not students:
                raise PaymentProblem('Say how many students this covers.', code='students_required')
            blocks = blocks_for(students)
            amount = price_for_blocks(blocks) * 100
            covers_from = max(window['resumes_on'], today)
            access_until = window['access_until']
            kind = 'grant'

        payment = apply_manual_payment(
            school=school, blocks=blocks, academic_year=academic_year, term=term,
            access_until=access_until, covers_from=covers_from, amount=amount,
            kind=kind, note=data.get('note', ''), user=request.user,
        )
        return Response(PaymentSerializer(payment).data, status=status.HTTP_201_CREATED)


class BlocksOverrideView(APIView):
    """Change a school's paid blocks without a payment (super admin, logged automatically)."""

    permission_classes = (permissions.IsAuthenticated, IsSuperAdmin)

    def post(self, request, pk):
        school = get_object_or_404(School, pk=pk)
        try:
            blocks = int(request.data.get('blocks'))
        except (TypeError, ValueError):
            raise PaymentProblem('Pass a whole number of blocks.', code='bad_blocks')
        if blocks < 1:
            # Zero would switch the student limit off.
            raise PaymentProblem('A school needs at least one block.', code='bad_blocks')
        school.paid_blocks = blocks
        school.save(update_fields=['paid_blocks'])      # the audit signal logs this write
        invalidate(school.pk)
        return Response({'blocks': blocks, 'limit': limit_for_blocks(blocks),
                         'capacity': capacity(School.objects.get(pk=school.pk))})


class RemindersCronView(APIView):
    """The scheduled job. Vercel calls it with the shared secret."""

    authentication_classes = ()
    permission_classes = (permissions.AllowAny,)
    throttle_classes = ()

    def get(self, request):
        # Vercel sends CRON_SECRET; other schedulers can use BILLING_CRON_SECRET.
        secrets_ = [s for s in (getattr(settings, 'BILLING_CRON_SECRET', ''),
                                getattr(settings, 'CRON_SECRET', '')) if s]
        sent = request.META.get('HTTP_AUTHORIZATION', '').removeprefix('Bearer ').encode()
        if not any(hmac.compare_digest(sent, s.encode()) for s in secrets_):
            return Response({'detail': 'Not found.'}, status=status.HTTP_404_NOT_FOUND)
        from .reminders import run
        return Response({'sent': run()})
