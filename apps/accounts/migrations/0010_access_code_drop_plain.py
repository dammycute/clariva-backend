from django.db import migrations, models
import fernet_fields.fields


class Migration(migrations.Migration):

    dependencies = [('accounts', '0009_access_code_encrypt_rows')]

    operations = [
        migrations.RemoveField(model_name='studentaccesscode', name='code'),
        migrations.RenameField(model_name='studentaccesscode', old_name='code_encrypted', new_name='code'),
        migrations.AlterField(
            model_name='studentaccesscode',
            name='code',
            field=fernet_fields.fields.EncryptedCharField(max_length=12),
        ),
        migrations.AlterField(
            model_name='studentaccesscode',
            name='code_hash',
            field=models.CharField(db_index=True, editable=False, max_length=64, unique=True),
        ),
    ]
