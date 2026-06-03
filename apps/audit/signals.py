from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.contenttypes.models import ContentType
from .models import ActivityLog

IGNORE_MODELS = {'ActivityLog', 'Session', 'LogEntry', 'ContentType'}

def log_activity(sender, instance, action, request=None, **kwargs):
    model_name = sender.__name__
    if model_name in IGNORE_MODELS:
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
        ip_address=getattr(request, 'META', {}).get('REMOTE_ADDR', '')[:45] if request else None,
    )

class RequestMiddleware:
    _thread_local = None

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        setattr(request, '_audit_user', request.user)
        return self.get_response(request)
