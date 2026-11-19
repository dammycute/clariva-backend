from datetime import timedelta

from django.db import migrations


def carry_over(apps, schema_editor):
    Exam = apps.get_model('exams', 'Exam')
    ExamSession = apps.get_model('exams', 'ExamSession')

    # One class becomes a list of one. Existing exams keep who they were for.
    for exam in Exam.objects.exclude(class_group__isnull=True):
        exam.classes.add(exam.class_group_id)

    # Old status words map onto the new ones.
    Exam.objects.filter(status='ongoing').update(status='published')
    Exam.objects.filter(status='completed').update(status='closed')

    # Attempts that are running now need a deadline so the server can close them.
    for session in ExamSession.objects.filter(status='active', deadline__isnull=True,
                                              started_at__isnull=False).select_related('exam'):
        deadline = session.started_at + timedelta(minutes=session.exam.duration_mins)
        if session.exam.end_time and session.exam.end_time < deadline:
            deadline = session.exam.end_time
        session.deadline = deadline
        session.save(update_fields=['deadline'])


class Migration(migrations.Migration):

    dependencies = [
        ('exams', '0002_cbt_v2'),
    ]

    operations = [
        migrations.RunPython(carry_over, migrations.RunPython.noop),
    ]
