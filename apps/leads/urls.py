from django.urls import path

from .views import DemoRequestListView, DemoRequestView

urlpatterns = [
    path('demo/', DemoRequestView.as_view(), name='demo-request'),
    path('demo-requests/', DemoRequestListView.as_view(), name='demo-request-list'),
]
