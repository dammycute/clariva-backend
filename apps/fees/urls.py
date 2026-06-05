from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FeeItemViewSet, FeeInvoiceViewSet
from .bursary_views import bursary_summary

router = DefaultRouter()
router.register(r'items', FeeItemViewSet)
router.register(r'invoices', FeeInvoiceViewSet)
urlpatterns = router.urls + [
    path('bursary-summary/', bursary_summary, name='bursary-summary'),
]
