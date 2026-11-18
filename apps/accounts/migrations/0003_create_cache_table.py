from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    """Table used by the database cache (CACHE_BACKEND=db): portal OTP codes and rate limits."""
    call_command('createcachetable', 'django_cache', database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0002_alter_user_options'),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
