from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import SchoolViewSet, system_stats

router = DefaultRouter()
router.register(r'', SchoolViewSet)
urlpatterns = [
    path('system-stats/', system_stats, name='system-stats'),
] + router.urls
