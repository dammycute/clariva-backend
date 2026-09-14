from rest_framework.routers import DefaultRouter
from .views import ReportCardViewSet

router = DefaultRouter()
router.register(r'report-cards', ReportCardViewSet)
urlpatterns = router.urls
