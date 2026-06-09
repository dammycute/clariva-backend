from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import School

NERDC_SUBJECTS = {
    'JSS1': [
        ('English', 'ENG'), ('Mathematics', 'MTH'), ('Basic Science', 'BSC'),
        ('Basic Technology', 'BKT'), ('Social Studies', 'SOS'), ('Civic Education', 'CVE'),
        ('Business Studies', 'BUS'), ('Agricultural Science', 'AGR'), ('Home Economics', 'HEC'),
        ('Computer Studies', 'CSC'), ('Physical & Health Education', 'PHE'),
        ('French', 'FRN'), ('Christian Religious Studies', 'CRS'),
        ('Creative Arts', 'CRA'), ('Music', 'MUS'),
    ],
    'JSS2': [
        ('English', 'ENG'), ('Mathematics', 'MTH'), ('Basic Science', 'BSC'),
        ('Basic Technology', 'BKT'), ('Social Studies', 'SOS'), ('Civic Education', 'CVE'),
        ('Business Studies', 'BUS'), ('Agricultural Science', 'AGR'), ('Home Economics', 'HEC'),
        ('Computer Studies', 'CSC'), ('Physical & Health Education', 'PHE'),
        ('French', 'FRN'), ('Christian Religious Studies', 'CRS'),
        ('Creative Arts', 'CRA'), ('Music', 'MUS'),
    ],
    'JSS3': [
        ('English', 'ENG'), ('Mathematics', 'MTH'), ('Basic Science', 'BSC'),
        ('Basic Technology', 'BKT'), ('Social Studies', 'SOS'), ('Civic Education', 'CVE'),
        ('Business Studies', 'BUS'), ('Agricultural Science', 'AGR'), ('Home Economics', 'HEC'),
        ('Computer Studies', 'CSC'), ('Physical & Health Education', 'PHE'),
        ('French', 'FRN'), ('Christian Religious Studies', 'CRS'),
        ('Creative Arts', 'CRA'), ('Music', 'MUS'),
    ],
    'SS1': [
        ('English', 'ENG'), ('Mathematics', 'MTH'), ('Biology', 'BIO'),
        ('Chemistry', 'CHM'), ('Physics', 'PHY'), ('Further Mathematics', 'FUR'),
        ('Geography', 'GEO'), ('Government', 'GOV'), ('Economics', 'ECO'),
        ('Commerce', 'COM'), ('Accounting', 'ACC'), ('Literature in English', 'LIT'),
        ('Agricultural Science', 'AGR'), ('Computer Studies', 'CSC'),
        ('Civic Education', 'CVE'), ('Physical & Health Education', 'PHE'),
        ('Christian Religious Studies', 'CRS'), ('History', 'HIS'),
    ],
    'SS2': [
        ('English', 'ENG'), ('Mathematics', 'MTH'), ('Biology', 'BIO'),
        ('Chemistry', 'CHM'), ('Physics', 'PHY'), ('Further Mathematics', 'FUR'),
        ('Geography', 'GEO'), ('Government', 'GOV'), ('Economics', 'ECO'),
        ('Commerce', 'COM'), ('Accounting', 'ACC'), ('Literature in English', 'LIT'),
        ('Agricultural Science', 'AGR'), ('Computer Studies', 'CSC'),
        ('Civic Education', 'CVE'), ('Physical & Health Education', 'PHE'),
        ('Christian Religious Studies', 'CRS'), ('History', 'HIS'),
    ],
    'SS3': [
        ('English', 'ENG'), ('Mathematics', 'MTH'), ('Biology', 'BIO'),
        ('Chemistry', 'CHM'), ('Physics', 'PHY'), ('Further Mathematics', 'FUR'),
        ('Geography', 'GEO'), ('Government', 'GOV'), ('Economics', 'ECO'),
        ('Commerce', 'COM'), ('Accounting', 'ACC'), ('Literature in English', 'LIT'),
        ('Agricultural Science', 'AGR'), ('Computer Studies', 'CSC'),
        ('Civic Education', 'CVE'), ('Physical & Health Education', 'PHE'),
        ('Christian Religious Studies', 'CRS'), ('History', 'HIS'),
    ],
}


def create_default_subjects(school):
    from apps.exams.models import Subject
    created_count = 0
    for year_group, subjects in NERDC_SUBJECTS.items():
        for name, code in subjects:
            _, was_created = Subject.objects.get_or_create(
                school=school,
                name=name,
                year_group=year_group,
                defaults={'code': code, 'is_core': True},
            )
            if was_created:
                created_count += 1
    return created_count


@receiver(post_save, sender=School)
def school_post_save(sender, instance, created, **kwargs):
    if created:
        create_default_subjects(instance)
