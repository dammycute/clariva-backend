from django.apps import AppConfig

class SchoolsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.schools'

    def ready(self):
        import apps.schools.signals
