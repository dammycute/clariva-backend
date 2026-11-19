from django.core.management.base import BaseCommand, CommandError

from apps.fees.services import FeeService
from apps.schools.models import School


class Command(BaseCommand):
    help = ("Join a school's separate unpaid invoices (same student, same term) into one invoice per "
            "student. Invoices with any payment are never touched. Shows what would change unless "
            "--apply is given.")

    def add_arguments(self, parser):
        parser.add_argument('subdomain', help='The school subdomain, e.g. queens-college')
        parser.add_argument('--apply', action='store_true', help='Make the change. Without it, nothing is changed.')

    def handle(self, *args, subdomain, apply, **options):
        try:
            school = School.objects.get(subdomain=subdomain)
        except School.DoesNotExist:
            raise CommandError(f'No school with subdomain "{subdomain}".')
        result = FeeService.merge_open_invoices(school, apply=apply)
        verb = 'Merged' if apply else 'Would merge'
        self.stdout.write(f"{verb}: {result['students']} students, {result['invoices_removed']} extra invoices "
                          f"{'removed' if apply else 'would be removed'} for {school.name}.")
        if not apply:
            self.stdout.write('Nothing was changed. Run again with --apply to do it.')
