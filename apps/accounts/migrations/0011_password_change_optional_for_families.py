from django.db import migrations


def stop_forcing(apps, schema_editor):
    users = apps.get_model('accounts', 'User').objects.using(schema_editor.connection.alias)
    users.filter(role__in=('student', 'parent'), must_change_password=True).update(must_change_password=False)


class Migration(migrations.Migration):

    dependencies = [('accounts', '0010_access_code_drop_plain')]

    operations = [migrations.RunPython(stop_forcing, migrations.RunPython.noop)]
