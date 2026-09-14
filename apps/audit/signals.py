from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from .models import ActivityLog
import threading

_IGNORE_MODELS = {'ActivityLog', 'Session', 'LogEntry', 'ContentType', 'Token'}
_thread_local = threading.local()


def get_current_request():
    return getattr(_thread_local, 'request', None)


def log_activity(sender, instance, action, request=None, **kwargs):
    model_name = sender.__name__
    if model_name in _IGNORE_MODELS:
        return
    user = getattr(request, 'user', None) if request else None
    if not user or not user.is_authenticated:
        return
    school = getattr(user, 'school', None)
    ActivityLog.objects.create(
        school=school,
        user=user,
        action=action,
        model_name=model_name,
        object_id=str(instance.pk) if instance.pk else None,
        object_repr=str(instance)[:255],
        ip_address=request.META.get('REMOTE_ADDR', '')[:45] if request else None,
    )


# Auto-log all model saves and deletes (excluding ignored models)
ALL_MODELS = None  # Will be populated after Django apps are ready


@receiver(post_save)
def auto_log_save(sender, instance, created, **kwargs):
    if sender.__name__ in _IGNORE_MODELS:
        return
    request = get_current_request()
    action = 'create' if created else 'update'
    log_activity(sender, instance, action, request)


@receiver(post_delete)
def auto_log_delete(sender, instance, **kwargs):
    if sender.__name__ in _IGNORE_MODELS:
        return
    request = get_current_request()
    log_activity(sender, instance, 'delete', request)


class RequestMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _thread_local.request = request
        response = self.get_response(request)
        return response
