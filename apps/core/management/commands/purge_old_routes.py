"""
Management command: purge_old_routes

Deletes RouteCache records older than N days (default: 30).
Safe to run as a weekly cron job.

Usage:
    python manage.py purge_old_routes
    python manage.py purge_old_routes --days 7
"""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.route.models import RouteCache


class Command(BaseCommand):
    help = "Delete RouteCache records older than --days (default: 30)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=30,
            help="Delete records older than this many days (default: 30)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print how many records would be deleted without deleting them",
        )

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(days=options["days"])
        qs = RouteCache.objects.filter(created_at__lt=cutoff)
        count = qs.count()

        if options["dry_run"]:
            self.stdout.write(
                f"[dry-run] Would delete {count} route cache record(s) older than "
                f"{options['days']} days."
            )
            return

        deleted, _ = qs.delete()
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {deleted} route cache record(s) older than {options['days']} days."
            )
        )
