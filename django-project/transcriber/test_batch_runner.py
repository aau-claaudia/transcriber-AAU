import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import uuid
import fcntl
import shutil
import wave
import zipfile
from pathlib import Path

from transcriber.batch_runner import run_batch, read_transcript


class BatchRunnerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.old_umask = os.umask(0o077)
        self.addCleanup(os.umask, self.old_umask)
        self.root = Path(temporary.name)
        self.workspace = self.root / str(uuid.uuid4())
        (self.workspace / 'input').mkdir(parents=True)
        (self.workspace / 'input/audio.wav').write_bytes(b'audio')
        self.manifest = [{'name': 'Speech.wav', 'path': 'input/audio.wav', 'size': 5, 'source': 'upload'}]
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        self.publish = self.root / 'media'
        self.worker = [sys.executable, str(Path(__file__).with_name('fake_worker.py'))]

    def run_worker(self, outcome='success'):
        return run_batch(self.workspace, self.publish, 'whisper/base', 'auto', 1,
                         self.worker + ['--test-outcome', outcome])

    def test_publishes_editor_compatible_results_and_manifest(self):
        completion = self.run_worker()
        result = self.publish / completion['results'][0]['directory']
        edited = json.loads((result / 'data/edited_output.json').read_text())
        self.assertEqual(edited['lines'][0]['id'], 0)
        self.assertEqual(edited['lines'][0]['speakerDesignation'], 'Speaker 1')
        self.assertTrue(edited['test_worker'])
        self.assertEqual(result.name, 'Speech_base_auto')
        self.assertEqual(result.parent, self.publish)
        self.assertEqual((result / 'data/Speech.wav').read_bytes(), b'audio')
        expected = {f'Speech_base_en.{extension}' for extension in
                    ('aud', 'csv', 'docx', 'dote.json', 'json', 'srt', 'tsv', 'txt', 'vtt')}
        expected.update(f'Speech_base_en_merged.{extension}' for extension in
                        ('csv', 'docx', 'dote.json', 'srt', 'vtt'))
        transcripts = result / 'TRANSCRIPTIONS'
        self.assertEqual({path.name for path in transcripts.iterdir()},
                         expected | {'files.zip', 'transcribe.log', 'transcriber_output.txt'})
        with zipfile.ZipFile(transcripts / 'files.zip') as archive:
            self.assertEqual(set(archive.namelist()), expected)
        original = json.loads((transcripts / 'Speech_base_en.dote.json').read_text())
        self.assertNotIn('id', original['lines'][0])
        self.assertEqual((transcripts / 'Speech_base_en.txt').read_text(), 'Synthetic test output only.')
        self.assertEqual((self.workspace / 'input/audio.wav').read_bytes(), b'audio')
        self.assertEqual(json.loads((self.workspace / 'completion.json').read_text()), completion)
        self.assertEqual(stat.S_IMODE((result / 'data/edited_output.json').stat().st_mode), 0o600)
        self.assertEqual(json.loads((self.workspace / 'progress.json').read_text())['state'], 'succeeded')

    def test_failed_missing_and_malformed_outputs_never_publish(self):
        for outcome in ('fail', 'missing', 'malformed'):
            with self.subTest(outcome=outcome), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                self.run_worker(outcome)
            self.assertFalse((self.publish / self.workspace.name).exists())
            self.assertFalse((self.workspace / 'completion.json').exists())
            self.assertEqual(list(self.publish.iterdir()), [])
        self.assertTrue((self.workspace / 'logs/worker.log').is_file())

    def test_timeout_never_publishes(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_batch(self.workspace, self.publish, 'whisper/base', 'auto', 1,
                      self.worker, timeout=0.000001)
        self.assertFalse((self.publish / self.workspace.name).exists())
        self.assertFalse((self.workspace / 'completion.json').exists())

    def test_exclusive_runner_lock(self):
        with (self.workspace / 'runner.lock').open('a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            with self.assertRaises(ValueError):
                self.run_worker()

    def test_multiple_files_publish_as_one_batch(self):
        (self.workspace / 'input/second.wav').write_bytes(b'second')
        self.manifest.append({'name': 'Second.wav', 'path': 'input/second.wav', 'size': 6, 'source': 'hpc'})
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        self.assertEqual(len(self.run_worker()['results']), 2)

    def test_real_worker_model_and_output_naming(self):
        from unittest.mock import patch
        def worker(command, workspace, log, timeout):
            self.assertEqual(command[command.index('-m') + 1], 'base')
            output = Path(command[command.index('-o') + 1])
            transcript = {'lines': [{'startTime':'00:00:00.000', 'endTime':'00:00:01.000',
                                    'speakerDesignation':'Speaker 1', 'text':'Test'}]}
            for suffix, formats in [('', ('aud', 'csv', 'docx', 'dote.json', 'json', 'srt', 'tsv', 'txt', 'vtt')),
                                    ('_merged', ('csv', 'docx', 'dote.json', 'srt', 'vtt'))]:
                for extension in formats:
                    (output / f'Speech_base_en{suffix}.{extension}').write_text(json.dumps(transcript))
            (output / 'files.zip').write_bytes(b'archive')
            (output / 'transcribe.log').write_text('log')
        with patch('transcriber.batch_runner.run_command', side_effect=worker):
            self.assertEqual(len(self.run_worker()['results']), 1)

    def test_configured_image_ffmpeg_command(self):
        from unittest.mock import patch
        (self.workspace / 'input/audio.wav').rename(self.workspace / 'input/audio.m4a')
        self.manifest[0]['path'] = 'input/audio.m4a'
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        def execute(command, workspace, log, timeout):
            if command[:2] == ['/adapter', '--ffmpeg']:
                Path(command[-1]).write_bytes(b'converted')
            else:
                output = Path(command[command.index('-o') + 1])
                for extension in ('aud', 'csv', 'docx', 'dote.json', 'json', 'srt', 'tsv', 'txt', 'vtt'):
                    (output / f'Speech_base_en.{extension}').write_text(json.dumps({'lines': []}))
                (output / 'files.zip').write_bytes(b'archive')
                (output / 'transcribe.log').write_text('log')
        with patch('transcriber.batch_runner.run_command', side_effect=execute):
            completion = run_batch(self.workspace, self.publish, 'whisper/base', 'en', 1,
                                   self.worker, ffmpeg_command=['/adapter', '--ffmpeg'])
        data = self.publish / completion['results'][0]['directory'] / 'data'
        self.assertEqual((data / 'converted_audio.mp3').read_bytes(), b'converted')

    def test_invalid_timestamps_rejected(self):
        path = self.root / 'bad.json'
        for start, end in [('00:99:00.000', '00:99:01.000'), ('00:00:02.000', '00:00:01.000')]:
            path.write_text(json.dumps({'lines': [{'startTime': start, 'endTime': end,
                                                  'speakerDesignation': 'Speaker 1', 'text': 'text'}]}))
            with self.assertRaises(ValueError):
                read_transcript(path)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg is not installed')
    def test_real_audio_conversion(self):
        wav_path = self.root / 'source.wav'
        with wave.open(str(wav_path), 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(8000)
            audio.writeframes(b'\x00\x00' * 8000)
        media = self.workspace / 'input/audio.m4a'
        subprocess.run(['ffmpeg', '-nostdin', '-y', '-i', str(wav_path), str(media)],
                       check=True, capture_output=True)
        (self.workspace / 'input/audio.wav').unlink()
        self.manifest[0].update(path='input/audio.m4a', name='source.m4a', size=media.stat().st_size)
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        completion = self.run_worker()
        data = self.publish / completion['results'][0]['directory'] / 'data'
        self.assertGreater((data / 'converted_audio.mp3').stat().st_size, 0)
        self.assertTrue(json.loads((data / 'metadata.json').read_text())['input_file_converted'])

    @unittest.skipUnless(shutil.which('ffmpeg'), 'FFmpeg is not installed')
    def test_bad_media_conversion_never_publishes(self):
        (self.workspace / 'input/audio.wav').rename(self.workspace / 'input/audio.m4a')
        self.manifest[0].update(path='input/audio.m4a')
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_worker()
        self.assertFalse((self.publish / self.workspace.name).exists())

    def test_does_not_overwrite_completed_results(self):
        self.run_worker()
        with self.assertRaises(ValueError):
            self.run_worker()

    def test_repeated_recording_uses_run_suffix_without_overwriting(self):
        existing = self.publish / 'Speech_base_auto'
        existing.mkdir(parents=True)
        (existing / 'keep.txt').write_text('user edits')
        second = self.publish / 'Speech_base_auto_run2'
        second.mkdir()
        completion = self.run_worker()
        self.assertEqual(completion['results'][0]['directory'], 'Speech_base_auto_run3')
        self.assertEqual((existing / 'keep.txt').read_text(), 'user edits')
        self.assertTrue(second.is_dir())

    def test_overlapping_and_special_input_names_remain_distinct(self):
        self.manifest[0]['name'] = 'Interview [1] #?.wav'
        (self.workspace / 'input/second.wav').write_bytes(b'second')
        self.manifest.append({'name': 'Interview [1] #?_extra.wav', 'path': 'input/second.wav',
                              'size': 6, 'source': 'upload'})
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        completion = self.run_worker()
        for result in completion['results']:
            transcripts = self.publish / result['directory'] / 'TRANSCRIPTIONS'
            self.assertEqual(len(list(transcripts.iterdir())), 17)
            with zipfile.ZipFile(transcripts / 'files.zip') as archive:
                self.assertEqual(len(archive.namelist()), 28)

    def test_parakeet_preserves_language_free_worker_filenames(self):
        completion = run_batch(self.workspace, self.publish, 'nvidia/parakeet-tdt-0.6b-v3',
                               'auto', 1, self.worker)
        result = self.publish / completion['results'][0]['directory']
        self.assertEqual(result.name, 'Speech_parakeet_auto')
        self.assertTrue((result / 'TRANSCRIPTIONS/Speech_parakeet.dote.json').is_file())

    def test_duplicate_input_stems_are_rejected(self):
        (self.workspace / 'input/second.mp3').write_bytes(b'second')
        self.manifest.append({'name': 'Speech.mp3', 'path': 'input/second.mp3',
                              'size': 6, 'source': 'upload'})
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaisesRegex(ValueError, 'distinct stems'):
            self.run_worker()

    def test_missing_artifacts_never_publish(self):
        from unittest.mock import patch
        from transcriber.batch_runner import run_command
        for name in ('Speech_base_en.docx', 'Speech_base_en_merged.vtt', 'files.zip', 'transcribe.log'):
            def incomplete_worker(command, workspace, log, timeout):
                run_command(command, workspace, log, timeout)
                output = Path(command[command.index('-o') + 1])
                (output / name).unlink()
            with self.subTest(name=name), patch('transcriber.batch_runner.run_command', side_effect=incomplete_worker):
                with self.assertRaises(ValueError):
                    self.run_worker()
            self.assertFalse(any(path.is_dir() for path in self.publish.iterdir()))
            self.assertFalse((self.workspace / 'completion.json').exists())

    def test_publication_failure_rolls_back_only_new_directories(self):
        from unittest.mock import patch
        from transcriber.batch_runner import write_json
        existing = self.publish / 'Speech_base_auto'
        existing.mkdir(parents=True)
        (existing / 'keep.txt').write_text('user edits')
        def fail_completion(path, payload):
            if path == self.workspace / 'completion.json':
                raise OSError('Deliberate publication failure')
            return write_json(path, payload)
        with patch('transcriber.batch_runner.write_json', side_effect=fail_completion):
            with self.assertRaises(OSError):
                self.run_worker()
        self.assertEqual([path.name for path in self.publish.iterdir() if path.is_dir()], ['Speech_base_auto'])
        self.assertEqual((existing / 'keep.txt').read_text(), 'user edits')
        self.assertFalse((self.workspace / 'completion.json').exists())

    def test_language_without_merged_outputs_preserves_standard_formats(self):
        from unittest.mock import patch
        from transcriber.batch_runner import run_command
        def without_merging(command, workspace, log, timeout):
            run_command(command, workspace, log, timeout)
            output = Path(command[command.index('-o') + 1])
            for artifact in output.glob('*_merged.*'):
                artifact.unlink()
        with patch('transcriber.batch_runner.run_command', side_effect=without_merging):
            completion = self.run_worker()
        transcripts = self.publish / completion['results'][0]['directory'] / 'TRANSCRIPTIONS'
        self.assertEqual(len(list(transcripts.iterdir())), 12)

    def test_rejects_symlink_and_manifest_escape(self):
        source = self.workspace / 'input/audio.wav'
        source.unlink()
        source.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            self.run_worker()
        self.manifest[0]['path'] = '../../etc/passwd'
        (self.workspace / 'input-manifest.json').write_text(json.dumps(self.manifest))
        with self.assertRaises(ValueError):
            self.run_worker()

    def test_cli_runs_without_django_environment(self):
        command = [sys.executable, '-S', str(Path(__file__).with_name('batch_runner.py')),
                   '--workspace', str(self.workspace), '--publish-root', str(self.publish),
                   '--model', 'whisper/base', '--worker-command', json.dumps(self.worker)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()