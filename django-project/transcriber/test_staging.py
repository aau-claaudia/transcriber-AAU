import json
import stat
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings

from .models import Transcription


class StagingTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        overrides = override_settings(JOBS_ROOT=self.root / 'jobs', MEDIA_ROOT=self.root / 'media',
                                      ALLOWED_HOSTS=['testserver'])
        overrides.enable()
        self.addCleanup(overrides.disable)

    def upload(self, **extra):
        data = {'files': SimpleUploadedFile('speech.wav', b'audio-data'),
                'model': 'whisper/base', 'language': 'auto'}
        data.update(extra)
        return self.client.post('/upload/', data)

    def test_upload_is_private_durable_and_recoverable(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        transcription = Transcription.objects.get(pk=response.json()['task_id'])
        self.assertEqual(transcription.state, 'staged')
        workspace = self.root / 'jobs' / str(transcription.id)
        staged = workspace / transcription.input_manifest[0]['path']
        self.assertEqual(staged.read_bytes(), b'audio-data')
        self.assertEqual(stat.S_IMODE(staged.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(workspace.stat().st_mode), 0o700)
        recovered = Client().get('/active-transcription/').json()['active_transcription']
        self.assertEqual(recovered['task_id'], str(transcription.id))
        self.assertNotIn('path', recovered['files'][0])
        self.assertEqual(self.client.get(f'/poll-transcription-status/{transcription.id}/').json()['job_state'], 'staged')

    def test_second_submission_conflicts(self):
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload().status_code, 409)
        self.assertEqual(Transcription.objects.count(), 1)

    def test_duplicate_names_rejected(self):
        response = self.upload(files=[SimpleUploadedFile('same.wav', b'audio'),
                                      SimpleUploadedFile('same.wav', b'other')])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Transcription.objects.count(), 0)

    def test_duplicate_stems_rejected_across_extensions(self):
        response = self.upload(files=[SimpleUploadedFile('same.wav', b'audio'),
                                      SimpleUploadedFile('same.mp3', b'other')])
        self.assertEqual(response.status_code, 400)
        self.assertEqual(Transcription.objects.count(), 0)

    def test_interrupted_write_fails_without_partial_workspace(self):
        with patch('django.core.files.uploadedfile.InMemoryUploadedFile.chunks', return_value=iter([b'a'])):
            self.assertEqual(self.upload().status_code, 400)
        transcription = Transcription.objects.get()
        self.assertEqual(transcription.state, 'failed')
        self.assertIsNone(transcription.active_slot)
        self.assertFalse((self.root / 'jobs' / str(transcription.id)).exists())

    def test_initialization_has_no_legacy_mount_or_gpu_detection(self):
        response = self.client.get('/get-initialization-data/').json()
        self.assertEqual(response['file_list'], [])
        self.assertFalse(response['mounted_folder'])
        self.assertEqual(response['available_memory'], 16)
        self.assertIn('cpu-test', response['resource_profiles'])

    def test_database_enforces_one_active_record(self):
        Transcription.objects.create(model='whisper/base')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transcription.objects.create(model='whisper/base')

    def test_active_record_cannot_have_null_slot(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Transcription.objects.create(model='whisper/base', active_slot=None)

    def test_cancel_requires_post_and_releases_slot(self):
        task_id = self.upload().json()['task_id']
        url = f'/stop_transcription_task/{task_id}/'
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).json()['state'], 'CANCELLED')
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertEqual(self.upload().status_code, 201)

    def test_invalid_input_leaves_no_record(self):
        for extra in ({'model': 'unknown'}, {'language': '; touch /tmp/unsafe'},
                      {'resource_profile': 'unknown'}, {'files': SimpleUploadedFile('bad.exe', b'audio')},
                      {'files': SimpleUploadedFile('empty.wav', b'')}, {'files': []},
                      {'file_meta_data': 'not-json'}, {'file_meta_data': json.dumps([{'name': 'speech.wav', 'size': 1}])}):
            with self.subTest(extra=extra):
                self.assertEqual(self.upload(**extra).status_code, 400)
        self.assertEqual(Transcription.objects.count(), 0)

    @override_settings(MAX_UPLOAD_FILE_BYTES=2)
    def test_file_limit(self):
        self.assertEqual(self.upload().status_code, 400)

    @override_settings(MAX_UPLOAD_BATCH_BYTES=2)
    def test_batch_limit(self):
        self.assertEqual(self.upload().status_code, 400)

    def test_staging_failure_releases_slot_and_removes_partial_files(self):
        with patch('transcriber.staging.json.dump', side_effect=OSError('disk full')):
            self.assertEqual(self.upload().status_code, 503)
        transcription = Transcription.objects.get()
        self.assertEqual(transcription.state, 'failed')
        self.assertIsNone(transcription.active_slot)
        self.assertFalse((self.root / 'jobs' / str(transcription.id)).exists())
        self.assertEqual(self.upload().status_code, 201)

    def test_missing_job_is_not_pending(self):
        self.assertEqual(self.client.get(f'/poll-transcription-status/{uuid.uuid4()}/').status_code, 404)

    def test_csrf_required_for_upload_and_cancel(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post('/upload/').status_code, 403)
        response = client.get('/get-initialization-data/')
        token = response.cookies['csrftoken'].value
        uploaded = client.post('/upload/', {'files': SimpleUploadedFile('test.wav', b'audio'),
                               'model': 'whisper/base'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(uploaded.status_code, 201)
        cancel_url = f"/stop_transcription_task/{uploaded.json()['task_id']}/"
        self.assertEqual(client.post(cancel_url).status_code, 403)
        self.assertEqual(client.post(cancel_url, HTTP_X_CSRFTOKEN=token).status_code, 200)

    def test_legacy_symlink_routes_disabled(self):
        self.assertEqual(self.client.post('/link-files/').status_code, 410)
        self.assertEqual(self.client.post('/remove-link/').status_code, 410)