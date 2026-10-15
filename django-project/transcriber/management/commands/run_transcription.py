import json
import signal
import sys
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from transcriber.batch_runner import run_batch
from transcriber.models import Transcription


class Command(BaseCommand):
    help = 'Explicitly run a staged batch. --fake produces synthetic transcripts, not speech recognition.'

    def add_arguments(self, parser):
        parser.add_argument('transcription_id')
        worker = parser.add_mutually_exclusive_group(required=True)
        worker.add_argument('--fake', action='store_true')
        worker.add_argument('--worker-command', help='Trusted JSON command argument list')
        parser.add_argument('--threads', type=int, default=1)
        parser.add_argument('--timeout', type=float, default=3600)
        parser.add_argument('--test-outcome', choices=['success', 'fail', 'missing', 'malformed'], default='success')

    def handle(self, *args, **options):
        try:
            record = Transcription.objects.get(pk=options['transcription_id'])
        except (Transcription.DoesNotExist, ValueError) as error:
            raise CommandError('Unknown transcription UUID') from error
        if options['fake']:
            worker = [sys.executable, str(Path(__file__).parents[2] / 'fake_worker.py'),
                      '--test-outcome', options['test_outcome']]
        else:
            try:
                worker = json.loads(options['worker_command'])
            except ValueError as error:
                raise CommandError('Worker command must be a JSON argument list') from error
        if not isinstance(worker, list) or not worker or not all(isinstance(arg, str) and arg for arg in worker):
            raise CommandError('Worker command must be a nonempty argument list')
        if not Transcription.objects.filter(pk=record.pk, state='staged').update(
            state='running', updated_at=timezone.now(), failure_detail='',
        ):
            raise CommandError('Only staged batches can be run; completed batches are never overwritten')
        previous_handler = signal.getsignal(signal.SIGTERM)
        def terminate(signum, frame):
            raise InterruptedError('Runner terminated')
        signal.signal(signal.SIGTERM, terminate)
        try:
            completion = run_batch(settings.JOBS_ROOT / str(record.id), settings.MEDIA_ROOT,
                                   record.model, record.language, options['threads'], worker, options['timeout'])
        except (Exception, KeyboardInterrupt) as error:
            Transcription.objects.filter(pk=record.id, state='running').update(
                state='failed', active_slot=None, failure_detail='Batch execution failed; see private worker logs.',
                updated_at=timezone.now(), finished_at=timezone.now(),
            )
            raise CommandError(f'Batch execution failed: {type(error).__name__}') from error
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
        Transcription.objects.filter(pk=record.id, state='running').update(
            state='succeeded', active_slot=None, updated_at=timezone.now(), finished_at=timezone.now(),
        )
        self.stdout.write(f"Published {len(completion['results'])} file result(s) for {record.id}")