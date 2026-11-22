from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from .views import health_check

urlpatterns = [
    path('health/', health_check, name='health-check'),
    path('api/auth/', include('apps.accounts.urls')),
    path('api/schools/', include('apps.schools.urls')),
    path('api/students/', include('apps.students.urls')),
    path('api/classes/', include('apps.classes.urls')),
    path('api/staff/', include('apps.staff.urls')),
    path('api/fees/', include('apps.fees.urls')),
    path('api/locations/', include('apps.locations.urls')),
    path('api/attendance/', include('apps.attendance.urls')),
    path('api/grades/', include('apps.grades.urls')),
    path('api/exams/', include('apps.exams.urls')),
    path('api/timetable/', include('apps.timetable.urls')),
    path('api/results/', include('apps.results.urls')),
    path('api/comms/', include('apps.comms.urls')),
    path('api/audit/', include('apps.audit.urls')),
    path('api/portal/', include('apps.guardian.urls')),
    path('api/leads/', include('apps.leads.urls')),
]

if settings.ENABLE_ADMIN:
    urlpatterns.insert(0, path('admin/', admin.site.urls))
