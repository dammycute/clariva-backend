from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AdminPaymentListView, AdminSchoolBillingView, BillingStatusView, BlocksOverrideView,
    InitializePaymentView, ManualPaymentView, PaymentListView, PaystackWebhookView,
    RemindersCronView, TermCalendarViewSet, VerifyPaymentView,
)

router = DefaultRouter()
router.register(r'calendars', TermCalendarViewSet, basename='term-calendar')

urlpatterns = [
    path('status/', BillingStatusView.as_view(), name='billing-status'),
    path('payments/', PaymentListView.as_view(), name='billing-payments'),
    path('payments/initialize/', InitializePaymentView.as_view(), name='billing-initialize'),
    path('payments/verify/', VerifyPaymentView.as_view(), name='billing-verify'),
    path('webhook/', PaystackWebhookView.as_view(), name='billing-webhook'),
    path('admin/payments/', AdminPaymentListView.as_view(), name='billing-admin-payments'),
    path('admin/payments/manual/', ManualPaymentView.as_view(), name='billing-manual-payment'),
    path('admin/schools/<uuid:pk>/', AdminSchoolBillingView.as_view(), name='billing-admin-school'),
    path('admin/schools/<uuid:pk>/blocks/', BlocksOverrideView.as_view(), name='billing-admin-blocks'),
    path('cron/reminders/', RemindersCronView.as_view(), name='billing-cron-reminders'),
    path('', include(router.urls)),
]
