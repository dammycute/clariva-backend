from django.core.management.base import BaseCommand

from apps.billing.reminders import run


class Command(BaseCommand):
    help = 'Send the renewal and grace reminders that are due today.'

    def handle(self, *args, **options):
        sent = run()
        self.stdout.write(self.style.SUCCESS(f'{sent} reminder(s) sent'))
