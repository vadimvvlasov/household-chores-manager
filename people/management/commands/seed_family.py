from django.core.management.base import BaseCommand

from people.seed import seed_default_family


class Command(BaseCommand):
    help = "Seed the 4 default placeholder family members (idempotent)."

    def handle(self, *args, **options):
        seed_default_family()
        self.stdout.write(self.style.SUCCESS("Seeded default family members."))
