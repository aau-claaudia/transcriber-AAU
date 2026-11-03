import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .models import Transcription
from .staging import stage_uploads, transcription_status
from .slurm import submit, reconcile, cancel, SchedulerError


class SlurmTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        overrides = override_settings(JOBS_ROOT=self.root / 'jobs', MEDIA_ROOT=self.root / 'media',
            TRANSCRIBER_SLURM_ENABLED=True, SLURM_COMMAND_PREFIX=[], SLURM_RPC_TIMEOUT=10,
            TRANSCRIBER_COMPUTE_PYTHON='/usr/bin/python3',
            TRANSCRIBER_RUNNER_PATH='/shared/batch_runner.py',
            TRANSCRIBER_WORKER_COMMAND=['/usr/bin/python3', '/shared/fake_worker.py'])
        overrides.enable()
        self.addCleanup(overrides.disable)
        with override_settings(TRANSCRIBER_SLURM_ENABLED=False):
            self.record = stage_uploads([SimpleUploadedFile('test.wav', b'audio')], 'whisper/base', 'auto', 'cpu-test')
        self.name = f'transcriber-{self.record.id}'

    def test_submission_and_no_duplicate(self):
        with patch('transcriber.slurm.call_slurm', return_value='123;hpc\n') as call:
            submit(self.record)
            submit(self.record)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(self.record.slurm_job_id, '123')
        self.assertEqual(self.record.state, 'queued')
        args, script = call.call_args.args
        self.assertIn('--nodes=1', args)
        self.assertIn('--mem=16G', args)
        self.assertIn('umask 077', script)
        self.assertNotIn('SECRET_KEY', script)

    def test_uncertain_submission_recovered_by_name(self):
        with patch('transcriber.slurm.call_slurm', side_effect=SchedulerError('lost response')):
            submit(self.record)
        self.assertEqual(self.record.state, 'submitting')
        with patch('transcriber.slurm.call_slurm', return_value=f'123|{self.name}|RUNNING\n') as call:
            reconcile(self.record)
        self.assertEqual(self.record.state, 'running')
        self.assertEqual(self.record.slurm_job_id, '123')
        self.assertEqual(call.call_args.args[0][0], 'squeue')

    def test_missing_records_never_resubmit(self):
        with patch('transcriber.slurm.call_slurm', return_value='bad response'):
            submit(self.record)
        with patch('transcriber.slurm.call_slurm', return_value='') as call:
            reconcile(self.record)
        self.assertEqual(self.record.state, 'submitting')
        self.assertEqual([args.args[0][0] for args in call.call_args_list], ['squeue', 'sacct'])
        self.assertEqual(self.record.active_slot, 1)

    def queued(self):
        with patch('transcriber.slurm.call_slurm', return_value='123'):
            submit(self.record)

    def test_running_status_uses_scheduler_start_and_manifest_sizes(self):
        from datetime import datetime, timezone
        self.queued()
        started = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
        self.record.input_manifest = [
            {'name': 'upload.wav', 'size': 1000000, 'source': 'upload'},
            {'name': 'selected.mp3', 'size': 2000000, 'source': 'hpc'},
        ]
        self.record.save()
        with patch('transcriber.slurm.call_slurm', return_value=f'123|{self.name}|RUNNING|2026-11-03T12:00:00\n'):
            reconcile(self.record)
        with patch('transcriber.staging.timezone.now', return_value=started.replace(minute=1)):
            status = transcription_status(self.record)
        self.assertEqual(status['slurm_job_id'], '123')
        self.assertEqual(status['slurm_started_at'], started.isoformat())
        self.assertEqual(status['estimated_duration_seconds'], 180)
        self.assertEqual(status['elapsed_seconds'], 60)

    def test_queued_status_ignores_predicted_start(self):
        self.queued()
        with patch('transcriber.slurm.call_slurm', return_value=f'123|{self.name}|PENDING|2026-11-04T12:00:00\n'):
            reconcile(self.record)
        status = transcription_status(self.record)
        self.assertEqual(status['job_state'], 'queued')
        self.assertIsNone(status['slurm_started_at'])
        self.assertIsNone(status['elapsed_seconds'])

    def test_accounting_start_survives_reload_and_elapsed_stops_at_finish(self):
        from datetime import datetime, timezone
        self.queued()
        with patch('transcriber.slurm.call_slurm', side_effect=[
            '', f'123|{self.name}|FAILED|1:0|2026-11-03T12:00:00\n',
        ]), patch('transcriber.slurm.timezone.now', return_value=datetime(2026, 11, 3, 12, 2, tzinfo=timezone.utc)):
            reconcile(self.record)
        reloaded = Transcription.objects.get(pk=self.record.pk)
        status = transcription_status(reloaded)
        self.assertEqual(status['slurm_started_at'], '2026-11-03T12:00:00+00:00')
        self.assertEqual(status['elapsed_seconds'], 120)
        self.assertEqual(status['state'], 'FAILURE')

    def test_unknown_or_malformed_start_does_not_break_reconciliation(self):
        self.queued()
        for timestamp in ['Unknown', 'N/A', '2026-99-99T12:00:00']:
            with self.subTest(timestamp=timestamp), patch('transcriber.slurm.call_slurm',
                return_value=f'123|{self.name}|RUNNING|{timestamp}\n'):
                reconcile(self.record)
            self.assertEqual(self.record.state, 'running')
            self.assertIsNone(self.record.slurm_started_at)

    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_initialization_and_poll_restore_scheduler_metadata(self):
        self.queued()
        with patch('transcriber.slurm.call_slurm', return_value=f'123|{self.name}|RUNNING|2026-11-03T12:00:00\n'):
            initialized = self.client.get('/get-initialization-data/').json()['active_transcription']
            polled = self.client.get(f'/poll-transcription-status/{self.record.id}/').json()
        for status in [initialized, polled]:
            self.assertEqual(status['slurm_job_id'], '123')
            self.assertEqual(status['slurm_started_at'], '2026-11-03T12:00:00+00:00')
            self.assertGreaterEqual(status['elapsed_seconds'], 0)
            self.assertAlmostEqual(status['estimated_duration_seconds'], 5 / 1000000 * 60)

    def test_scheduler_commands_use_utc_timestamps(self):
        from .slurm import call_slurm
        with patch('transcriber.slurm.subprocess.run') as run:
            run.return_value.stdout = ''
            call_slurm(['squeue'])
        self.assertEqual(run.call_args.kwargs['env']['TZ'], 'UTC')
        self.assertEqual(run.call_args.kwargs['env']['SLURM_TIME_FORMAT'], 'standard')

    def test_completed_requires_valid_manifest(self):
        self.queued()
        with patch('transcriber.slurm.call_slurm', side_effect=['', f'123|{self.name}|COMPLETED|0:0\n']):
            reconcile(self.record)
        self.assertEqual(self.record.active_slot, 1)
        self.assertNotEqual(self.record.state, 'succeeded')
        self.assertIsNotNone(self.record.scheduler_terminal_seen_at)
        with override_settings(SLURM_RESULT_GRACE_SECONDS=0), patch('transcriber.slurm.call_slurm',
            side_effect=['', f'123|{self.name}|COMPLETED|0:0\n']):
            reconcile(self.record)
        self.assertEqual(self.record.state, 'failed')
        self.assertIsNone(self.record.active_slot)

    def test_valid_completed_results_release_slot(self):
        from .batch_runner import run_batch
        import sys
        run_batch(self.root / 'jobs' / str(self.record.id), self.root / 'media',
                  self.record.model, self.record.language, 1,
                  [sys.executable, str(Path(__file__).with_name('fake_worker.py'))])
        self.queued()
        with patch('transcriber.slurm.call_slurm', side_effect=['', f'123|{self.name}|COMPLETED|0:0\n']):
            reconcile(self.record)
        self.assertEqual(self.record.state, 'succeeded')
        self.assertIsNone(self.record.active_slot)

    def test_failure_and_cancel_confirmed_by_scheduler(self):
        self.queued()
        with patch('transcriber.slurm.call_slurm', side_effect=['', f'123|{self.name}|TIMEOUT|0:15\n']):
            reconcile(self.record)
        self.assertEqual(self.record.state, 'failed')
        self.assertIsNone(self.record.active_slot)

    def test_completion_checks_flat_manifest_and_all_artifacts(self):
        from .batch_runner import run_batch
        from .slurm import complete_results
        import sys
        workspace = self.root / 'jobs' / str(self.record.id)
        completion = run_batch(workspace, self.root / 'media', self.record.model, self.record.language, 1,
                               [sys.executable, str(Path(__file__).with_name('fake_worker.py'))])
        self.assertEqual(complete_results(self.record), completion)
        manifest_path = workspace / 'completion.json'
        directory = completion['results'][0]['directory']
        completion['results'][0]['directory'] = '../outside'
        manifest_path.write_text(json.dumps(completion))
        with self.assertRaisesRegex(ValueError, 'Invalid result directory'):
            complete_results(self.record)
        completion['results'][0]['directory'] = directory
        manifest_path.write_text(json.dumps(completion))
        transcripts = self.root / 'media' / directory / 'TRANSCRIPTIONS'
        for name in ('test_base_en.csv', 'test_base_en_merged.vtt', 'files.zip',
                     'transcribe.log', 'transcriber_output.txt'):
            artifact = transcripts / name
            content = artifact.read_bytes()
            artifact.unlink()
            with self.subTest(name=name), self.assertRaises(ValueError):
                complete_results(self.record)
            artifact.write_bytes(content)
        moved = self.root / 'moved-transcriptions'
        transcripts.rename(moved)
        transcripts.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            complete_results(self.record)

    def test_cancel_keeps_slot_until_confirmed(self):
        self.queued()
        with patch('transcriber.slurm.call_slurm', side_effect=[f'123|{self.name}|RUNNING\n', '']) as call:
            cancel(self.record)
        self.assertEqual(self.record.state, 'cancelling')
        self.assertEqual(self.record.active_slot, 1)
        self.assertEqual(call.call_args.args[0][-1], '123')
        with patch('transcriber.slurm.call_slurm', side_effect=['', f'123|{self.name}|CANCELLED by 1|0:15\n']):
            reconcile(self.record)
        self.assertEqual(self.record.state, 'cancelled')
        self.assertIsNone(self.record.active_slot)

    def test_outage_does_not_release_active_slot(self):
        self.queued()
        with patch('transcriber.slurm.call_slurm', side_effect=SchedulerError('unavailable')):
            reconcile(self.record)
        self.assertEqual(self.record.state, 'queued')
        self.assertEqual(self.record.active_slot, 1)

    def test_purged_live_job_falls_back_to_accounting(self):
        import subprocess
        self.queued()
        cause = subprocess.CalledProcessError(1, ['squeue'], stderr='slurm_load_jobs error: Invalid job id specified')
        error = SchedulerError('Scheduler request failed')
        error.__cause__ = cause
        with patch('transcriber.slurm.call_slurm', side_effect=[error, f'123|{self.name}|FAILED|1:0\n']):
            reconcile(self.record)
        self.assertEqual(self.record.state, 'failed')
        self.assertIsNone(self.record.active_slot)

    def test_resource_injection_rejected_before_submission(self):
        self.record.resources['partition'] = 'gpu; touch /tmp/unsafe'
        with patch('transcriber.slurm.call_slurm') as call, self.assertRaises(ValueError):
            submit(self.record)
        call.assert_not_called()

    def test_small_memory_profile(self):
        self.record.resources['memory_mb'] = 500
        with patch('transcriber.slurm.call_slurm', return_value='123') as call:
            submit(self.record)
        self.assertIn('--mem=500M', call.call_args.args[0])

    @override_settings(ALLOWED_HOSTS=['testserver'])
    def test_complete_recordings_visible_before_scheduler_confirmation(self):
        from .batch_runner import run_batch
        import sys
        run_batch(self.root / 'jobs' / str(self.record.id), self.root / 'media',
                  self.record.model, self.record.language, 1,
                  [sys.executable, str(Path(__file__).with_name('fake_worker.py'))])
        self.assertEqual(len(self.client.get('/get-completed-transcriptions/').json()['result']), 17)

    def test_multiple_matching_jobs_require_operator_review(self):
        self.record.state = 'submitting'
        self.record.save()
        with patch('transcriber.slurm.call_slurm', return_value=f'1|{self.name}|RUNNING\n2|{self.name}|RUNNING\n'):
            reconcile(self.record)
        self.assertIn('operator', self.record.failure_detail)
        self.assertEqual(self.record.slurm_job_id, '')

    def test_upload_automatically_submits_when_enabled(self):
        Transcription.objects.filter(pk=self.record.pk).update(state='cancelled', active_slot=None)
        with patch('transcriber.slurm.call_slurm', return_value='456'):
            record = stage_uploads([SimpleUploadedFile('next.wav', b'audio')], 'whisper/base', 'auto', 'cpu-test')
        self.assertEqual(record.state, 'queued')
        self.assertEqual(record.slurm_job_id, '456')

    def test_new_upload_reconciles_finished_active_job(self):
        from .batch_runner import run_batch
        import sys
        self.queued()
        run_batch(self.root / 'jobs' / str(self.record.id), self.root / 'media',
                  self.record.model, self.record.language, 1,
                  [sys.executable, str(Path(__file__).with_name('fake_worker.py'))])
        with patch('transcriber.slurm.call_slurm', side_effect=[
            '', f'123|{self.name}|COMPLETED|0:0\n', '456']):
            next_record = stage_uploads([SimpleUploadedFile('next.wav', b'audio')],
                                       'whisper/base', 'auto', 'cpu-test')
        self.record.refresh_from_db()
        self.assertEqual(self.record.state, 'succeeded')
        self.assertEqual(next_record.slurm_job_id, '456')

    def test_reconciliation_command_without_browser(self):
        from django.core.management import call_command
        import io
        with patch('transcriber.slurm.call_slurm', return_value='456'):
            call_command('reconcile_transcriptions', stdout=io.StringIO())
        self.record.refresh_from_db()
        self.assertEqual(self.record.state, 'queued')

    def test_invalid_configuration_preserves_staged_inputs(self):
        from .slurm import schedule_ready
        with override_settings(TRANSCRIBER_WORKER_COMMAND=[]):
            schedule_ready(self.record)
        self.assertEqual(self.record.state, 'staged')
        self.assertTrue((self.root / 'jobs' / str(self.record.id) / 'input-manifest.json').exists())
        self.assertIn('configuration', self.record.failure_detail)