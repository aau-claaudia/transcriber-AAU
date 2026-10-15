import json
import io
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from .hpc_files import list_directory
from .models import Transcription
from .staging import prepare_existing_inputs


class ExistingInputTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source_root = self.root / 'sources'
        self.source_root.mkdir()
        self.source = self.source_root / 'existing.wav'
        self.source.write_bytes(b'existing audio')
        overrides = override_settings(INPUT_ROOTS={'home': str(self.source_root)},
                                      DATA_ROOT=self.root / 'private', JOBS_ROOT=self.root / 'jobs',
                                      MEDIA_ROOT=self.root / 'media', ALLOWED_HOSTS=['testserver'])
        overrides.enable()
        self.addCleanup(overrides.disable)
        self.token = list_directory('home')['entries'][0]['token']

    def submit(self, uploaded=False, tokens=None):
        data = {'model': 'whisper/base', 'language': 'auto',
                'existing_files': json.dumps([self.token] if tokens is None else tokens)}
        if uploaded:
            data['files'] = SimpleUploadedFile('upload.wav', b'uploaded audio')
        with patch('transcriber.staging.launch_preparation') as launch:
            response = self.client.post('/upload/', data)
        if response.status_code == 201:
            launch.assert_called_once()
        return response

    def test_existing_only_copy_and_original_preserved(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['job_state'], 'preparing')
        transcription = Transcription.objects.get()
        prepare_existing_inputs(transcription.id)
        transcription.refresh_from_db()
        self.assertEqual(transcription.state, 'staged')
        staged = self.root / 'jobs' / str(transcription.id) / transcription.input_manifest[0]['path']
        self.assertEqual(staged.read_bytes(), self.source.read_bytes())
        self.assertFalse(staged.is_symlink())
        self.source.write_bytes(b'edited after staging')
        self.assertEqual(staged.read_bytes(), b'existing audio')

    def test_mixed_uploads_and_existing_inputs(self):
        self.assertEqual(self.submit(uploaded=True).status_code, 201)
        transcription = Transcription.objects.get()
        prepare_existing_inputs(transcription.id)
        transcription.refresh_from_db()
        self.assertEqual(transcription.state, 'staged')
        self.assertEqual({entry['source'] for entry in transcription.input_manifest}, {'upload', 'hpc'})

    def test_retry_replaces_partial_copy(self):
        self.submit()
        transcription = Transcription.objects.get()
        destination = self.root / 'jobs' / str(transcription.id) / transcription.input_manifest[0]['path']
        destination.with_suffix('.wav.part').write_bytes(b'partial')
        prepare_existing_inputs(transcription.id)
        self.assertEqual(destination.read_bytes(), b'existing audio')
        self.assertFalse(destination.with_suffix('.wav.part').exists())

    def test_cancel_during_copy_does_not_publish_staged(self):
        self.submit()
        transcription = Transcription.objects.get()

        class CancelStream(io.BytesIO):
            def read(self, size=-1):
                Transcription.objects.filter(pk=transcription.id).update(state='cancelled', active_slot=None)
                return super().read(size)

        def open_cancel_stream(descriptor, mode):
            os.close(descriptor)
            return CancelStream(b'existing audio')

        with patch('transcriber.staging.os.fdopen', side_effect=open_cancel_stream):
            prepare_existing_inputs(transcription.id)
        transcription.refresh_from_db()
        self.assertEqual(transcription.state, 'cancelled')
        self.assertFalse(list((self.root / 'jobs' / str(transcription.id) / 'input').iterdir()))

    def test_source_mutation_during_copy_rejected(self):
        self.submit()
        transcription = Transcription.objects.get()
        with patch('transcriber.staging.os.fsync', side_effect=lambda descriptor: self.source.write_bytes(b'changed')):
            with self.assertRaises(ValueError):
                prepare_existing_inputs(transcription.id)
        transcription.refresh_from_db()
        self.assertEqual(transcription.state, 'failed')
        self.assertFalse(list((self.root / 'jobs' / str(transcription.id) / 'input').iterdir()))

    def test_launch_failure_releases_active_slot(self):
        with patch('transcriber.staging.launch_preparation', side_effect=OSError('cannot launch')):
            response = self.client.post('/upload/', {'model': 'whisper/base',
                                                    'existing_files': json.dumps([self.token])})
        self.assertEqual(response.status_code, 503)
        self.assertIsNone(Transcription.objects.get().active_slot)

    def test_changed_source_before_copy_fails_and_releases_slot(self):
        self.submit()
        transcription = Transcription.objects.get()
        self.source.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            prepare_existing_inputs(transcription.id)
        transcription.refresh_from_db()
        self.assertEqual(transcription.state, 'failed')
        self.assertIsNone(transcription.active_slot)

    def test_invalid_token_rejected_before_record_creation(self):
        self.assertEqual(self.submit(tokens=['invalid']).status_code, 400)
        self.assertFalse(Transcription.objects.exists())

    def test_duplicate_names_across_sources_rejected(self):
        response = self.client.post('/upload/', {'model': 'whisper/base',
            'existing_files': json.dumps([self.token]), 'files': SimpleUploadedFile('existing.wav', b'audio')})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Transcription.objects.exists())

    def test_non_list_selections_rejected(self):
        self.assertEqual(self.submit(tokens={}).status_code, 400)

    def test_cancel_does_not_delete_original_or_prepare_again(self):
        self.submit()
        transcription = Transcription.objects.get()
        self.assertEqual(self.client.post(f'/stop_transcription_task/{transcription.id}/').status_code, 200)
        prepare_existing_inputs(transcription.id)
        self.assertEqual(self.source.read_bytes(), b'existing audio')
        self.assertEqual(Transcription.objects.get().state, 'cancelled')

    def test_resume_pending_command(self):
        from django.core.management import call_command
        self.submit(uploaded=True)
        call_command('prepare_inputs', pending=True)
        self.assertEqual(Transcription.objects.get().state, 'staged')
        call_command('prepare_inputs', pending=True)

    @override_settings(MAX_UPLOAD_BATCH_BYTES=1)
    def test_existing_files_count_toward_limits(self):
        self.assertEqual(self.submit().status_code, 400)

    def test_directory_endpoint(self):
        response = self.client.get('/hpc-files/', {'root': 'home'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['entries'][0]['name'], 'existing.wav')
        self.assertEqual(self.client.get('/hpc-files/', {'root': 'home', 'path': '../'}).status_code, 400)
        self.assertEqual(self.client.post('/hpc-files/').status_code, 405)