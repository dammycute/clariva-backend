from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import StateViewSet, LGAViewSet

router = DefaultRouter()
router.register(r'states', StateViewSet)
router.register(r'lgas', LGAViewSet)
urlpatterns = router.urls
