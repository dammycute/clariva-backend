from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SchoolViewSet, portal_address, school_by_domain, system_stats

router = DefaultRouter()
router.register(r'', SchoolViewSet)
urlpatterns = [
    path('system-stats/', system_stats, name='system-stats'),
    path('by-domain/', school_by_domain, name='school-by-domain'),
    path('portal-address/', portal_address, name='school-portal-address'),
] + router.urls
