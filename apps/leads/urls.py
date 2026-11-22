from django.urls import path

from .views import DemoRequestView

urlpatterns = [path('demo/', DemoRequestView.as_view(), name='demo-request')]
