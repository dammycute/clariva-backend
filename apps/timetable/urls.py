from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import TimeTableViewSet

router = DefaultRouter()
router.register(r'timetables', TimeTableViewSet)
urlpatterns = router.urls
