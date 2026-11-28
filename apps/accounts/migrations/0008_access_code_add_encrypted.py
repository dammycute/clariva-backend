from django.db import migrations
import fernet_fields.fields


class Migration(migrations.Migration):

    dependencies = [('accounts', '0007_walkthrough_done')]

    operations = [
        migrations.AddField(
            model_name='studentaccesscode',
            name='code_encrypted',
            field=fernet_fields.fields.EncryptedCharField(max_length=12, null=True),
        ),
    ]
