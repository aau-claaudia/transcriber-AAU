import io
import json
import tempfile
from pathlib import Path

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings

from transcriber.models import Transcription
from transcriber.staging import stage_uploads


class RunTranscriptionTests(TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        overrides = override_settings(JOBS_ROOT=self.root / 'jobs', MEDIA_ROOT=self.root / 'media',
                                      ALLOWED_HOSTS=['testserver'])
        overrides.enable()
        self.addCleanup(overrides.disable)
        self.record = stage_uploads([SimpleUploadedFile('speech.wav', b'audio')],
                                    'whisper/base', 'auto', 'cpu-test')

    def run_fake(self, outcome='success'):
        call_command('run_transcription', str(self.record.id), fake=True,
                     test_outcome=outcome, stdout=io.StringIO())

    def test_fake_batch_visible_to_existing_editor_and_status(self):
        self.run_fake()
        self.record.refresh_from_db()
        self.assertEqual(self.record.state, 'succeeded')
        self.assertIsNone(self.record.active_slot)
        response = self.client.get(f'/poll-transcription-status/{self.record.id}/').json()
        self.assertEqual(response['state'], 'SUCCESS')
        self.assertEqual(len(response['result']), 17)
        result = response['result'][0]
        self.assertEqual(result['original_file_name'], 'speech.wav')
        self.assertEqual(result['model'], 'base')
        self.assertEqual(result['dir_name'], 'speech_base_auto')
        edited_url = result['edit_file_url'].replace('http://testserver', '')
        edited = json.loads(self.client.get(edited_url).content)
        self.assertTrue(edited['test_worker'])
        self.assertEqual(edited['lines'][0]['id'], 0)
        self.assertEqual(edited['lines'][0]['speakerDesignation'], 'Speaker 1')
        media_url = result['input_file_url'].replace('http://testserver', '')
        self.assertEqual(self.client.get(media_url).content, b'audio')

    def test_failed_worker_records_failure_without_results(self):
        with self.assertRaises(CommandError):
            self.run_fake('fail')
        self.record.refresh_from_db()
        self.assertEqual(self.record.state, 'failed')
        self.assertIsNone(self.record.active_slot)
        self.assertEqual(self.client.get('/get-completed-transcriptions/').json()['result'], [])
        self.assertIn('Deliberate fake-worker failure',
                      (self.root / 'jobs' / str(self.record.id) / 'logs/worker.log').read_text())

    def test_output_downloads_are_attachments_but_editor_and_audio_remain_inline(self):
        self.run_fake()
        results = self.client.get('/get-completed-transcriptions/').json()['result']
        for result in results:
            with self.subTest(name=result['file_name']):
                response = self.client.get(result['file_url'].replace('http://testserver', ''))
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Content-Disposition'],
                                 f'attachment; filename="{result["file_name"]}"')
        result = results[0]
        for key in ('input_file_url', 'edit_file_url'):
            response = self.client.get(result[key].replace('http://testserver', ''))
            self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        audio = self.client.get(result['input_file_url'].replace('http://testserver', ''),
                                HTTP_RANGE='bytes=0-3')
        self.assertEqual(audio.status_code, 206)
        self.assertEqual(audio.content, b'audi')

    def test_edit_and_export_generated_transcript(self):
        self.run_fake()
        directory = 'speech_base_auto'
        response = self.client.post('/edit-transcription-segment/',
            json.dumps({'dir_name': directory, 'payload': {
                'type': 'text_edit', 'segmentId': 0, 'newText': 'Edited synthetic transcript',
            }}), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        for output_format in ('json', 'txt', 'docx'):
            with self.subTest(output_format=output_format):
                exported = self.client.get('/export-file/', {
                    'dir_name': directory, 'target': 'edited_output', 'format': output_format,
                })
                self.assertEqual(exported.status_code, 200)
                self.assertGreater(len(exported.content), 0)
                if output_format != 'docx':
                    self.assertIn(b'Edited synthetic transcript', exported.content)

    def test_repeated_execution_does_not_overwrite_edits(self):
        self.run_fake()
        with self.assertRaises(CommandError):
            self.run_fake()
        self.assertEqual(Transcription.objects.get().state, 'succeeded')

    def test_cancelled_batch_cannot_run(self):
        self.client.post(f'/stop_transcription_task/{self.record.id}/')
        with self.assertRaises(CommandError):
            self.run_fake()

    def test_special_filename_download_urls_are_encoded(self):
        manifest = self.record.input_manifest
        manifest[0]['name'] = 'Interview #1?.wav'
        self.record.input_manifest = manifest
        self.record.save()
        workspace = self.root / 'jobs' / str(self.record.id)
        (workspace / 'input-manifest.json').write_text(json.dumps(manifest))
        self.run_fake()
        results = self.client.get('/get-completed-transcriptions/').json()['result']
        self.assertEqual(len(results), 17)
        for result in results:
            url = result['file_url'].replace('http://testserver', '')
            self.assertIn('%23', url)
            self.assertEqual(self.client.get(url).status_code, 200)