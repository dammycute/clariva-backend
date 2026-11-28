from django.db import migrations

from apps.base.encryption import hash_value


def encrypt_codes(apps, schema_editor):
    codes = apps.get_model('accounts', 'StudentAccessCode').objects.using(schema_editor.connection.alias)
    for row in codes.all().iterator():
        row.code_encrypted = row.code
        row.code_hash = hash_value(row.code)
        row.save(update_fields=['code_encrypted', 'code_hash'])


class Migration(migrations.Migration):

    dependencies = [('accounts', '0008_access_code_add_encrypted')]

    operations = [migrations.RunPython(encrypt_codes)]
