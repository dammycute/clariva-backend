from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import FeeItemViewSet, FeeInvoiceViewSet

router = DefaultRouter()
router.register(r'items', FeeItemViewSet)
router.register(r'invoices', FeeInvoiceViewSet)
urlpatterns = router.urls
