from django.core.management.base import BaseCommand, CommandError

from transcriber.models import Transcription
from transcriber.staging import prepare_existing_inputs


class Command(BaseCommand):
    help = 'Prepare existing HPC inputs; --pending retries interrupted preparation.'

    def add_arguments(self, parser):
        parser.add_argument('transcription_id', nargs='?')
        parser.add_argument('--pending', action='store_true')

    def handle(self, *args, **options):
        if options['pending']:
            identifiers = Transcription.objects.filter(state='preparing').values_list('id', flat=True)
        elif options['transcription_id']:
            identifiers = [options['transcription_id']]
        else:
            raise CommandError('Provide a transcription UUID or --pending')
        failed = False
        for identifier in identifiers:
            try:
                prepare_existing_inputs(identifier)
            except Exception:
                failed = True
                self.stderr.write(f'Preparation failed for {identifier}')
        if failed:
            raise CommandError('Some inputs could not be prepared')