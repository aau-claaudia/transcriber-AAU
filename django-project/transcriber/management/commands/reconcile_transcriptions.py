import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from transcriber.models import Transcription
from transcriber.slurm import enabled, reconcile


class Command(BaseCommand):
    help = 'Submit staged batches and reconcile active Slurm jobs independently of browser requests.'

    def add_arguments(self, parser):
        parser.add_argument('--watch', action='store_true')
        parser.add_argument('--interval', type=int, default=15)

    def handle(self, *args, **options):
        if not enabled():
            raise CommandError('Enable TRANSCRIBER_SLURM_ENABLED first')
        if options['interval'] < 5:
            raise CommandError('Polling interval must be at least 5 seconds')
        while True:
            close_old_connections()
            for record in Transcription.objects.filter(active_slot=1):
                reconciled = reconcile(record)
                self.stdout.write(f'{record.id}: {reconciled.state}')
            if not options['watch']:
                return
            time.sleep(options['interval'])