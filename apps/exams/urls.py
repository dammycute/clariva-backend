from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SubjectViewSet, StudentSubjectViewSet,
    ExamViewSet, QuestionViewSet, ExamSessionViewSet,
)

router = DefaultRouter()
router.register(r'subjects', SubjectViewSet)
router.register(r'student-subjects', StudentSubjectViewSet)
router.register(r'exams', ExamViewSet)
router.register(r'questions', QuestionViewSet)
router.register(r'sessions', ExamSessionViewSet)
urlpatterns = router.urls
