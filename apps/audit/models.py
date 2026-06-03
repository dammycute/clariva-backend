from django.db import models

class ActivityLog(models.Model):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE, null=True, blank=True)
    user = models.ForeignKey('accounts.User', on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=50)
    model_name = models.CharField(max_length=100)
    object_id = models.CharField(max_length=50, null=True, blank=True)
    object_repr = models.CharField(max_length=255, null=True, blank=True)
    changes = models.JSONField(null=True, blank=True)
    ip_address = models.CharField(max_length=45, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        verbose_name_plural = 'activity logs'

    def __str__(self):
        return f'{self.user} {self.action} {self.model_name}'
