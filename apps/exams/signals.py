from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Subject, Exam

COMPONENTS = [
    ('ca1', 'CA 1'),
    ('ca2', 'CA 2'),
    ('assignment', 'Assignment'),
    ('exam', 'Exam'),
]

@receiver(post_save, sender=Subject)
def auto_create_draft_exams(sender, instance, created, **kwargs):
    if not created:
        return
    if instance.grading_mode not in ('cbt', 'hybrid'):
        return
    if Exam.objects.filter(subject=instance).exists():
        return
    default_class = instance.school.class_set.filter(year_group=instance.year_group).first()
    for comp, comp_label in COMPONENTS:
        Exam.objects.create(
            school=instance.school,
            title=f'{instance.name} {comp_label}',
            subject=instance,
            class_group=default_class,
            duration_mins=30,
            pass_mark=40,
            status='draft',
            component=comp,
            term='1st Term',
            academic_year='2025/2026',
        )
