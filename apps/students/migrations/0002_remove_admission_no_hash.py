from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [('students', '0001_initial')]

    # The plain admission number sits beside it and is already unique, so the copy protected nothing.
    operations = [migrations.RemoveField(model_name='studentprofile', name='admission_no_hash')]
