from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AnnouncementViewSet, NotificationViewSet

router = DefaultRouter()
router.register(r'', AnnouncementViewSet)
router.register(r'notifications', NotificationViewSet)
urlpatterns = router.urls
