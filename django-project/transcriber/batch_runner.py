import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import uuid
import fcntl
import signal
from pathlib import Path


STANDARD_FORMATS = ('aud', 'csv', 'docx', 'dote.json', 'json', 'srt', 'tsv', 'txt', 'vtt')
MERGED_FORMATS = ('csv', 'docx', 'dote.json', 'srt', 'vtt')


def transcription_files(root, basename):
    names = [f'{basename}.{extension}' for extension in STANDARD_FORMATS]
    merged = [f'{basename}_merged.{extension}' for extension in MERGED_FORMATS]
    if any((root / name).exists() for name in merged):
        names.extend(merged)
    return [checked_path(root, name) for name in names]


def write_json(path, payload):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        os.chmod(temporary, 0o600)
        json.dump(payload, output, indent=2)
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def checked_path(root, relative):
    path = Path(relative)
    if path.is_absolute() or not path.parts or '..' in path.parts:
        raise ValueError('Invalid manifest path')
    candidate = root
    for part in path.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise ValueError('Symlink inputs and outputs are not supported')
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root):
        raise ValueError('Manifest file is missing or outside the workspace')
    return candidate


def private_directory(path):
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError('Runner directories must not use symlinks')
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_uid != os.getuid():
        raise ValueError('Runner directories must belong to the running user')
    path.chmod(0o700)
    return path.resolve()


def read_transcript(path):
    with path.open(encoding='utf-8') as source:
        transcript = json.load(source)
    if not isinstance(transcript, dict) or not isinstance(transcript.get('lines'), list):
        raise ValueError('Worker output must contain a transcript lines array')
    for index, line in enumerate(transcript['lines']):
        if not isinstance(line, dict):
            raise ValueError('Invalid transcript segment')
        for field in ('startTime', 'endTime', 'speakerDesignation', 'text'):
            if not isinstance(line.get(field), str):
                raise ValueError(f'Invalid transcript {field}')
        times = []
        for field in ('startTime', 'endTime'):
            if not re.fullmatch(r'\d{2,}:\d{2}:\d{2}\.\d{3}', line[field]):
                raise ValueError('Invalid transcript timestamp')
            hours, minutes, seconds = line[field].split(':')
            if int(minutes) >= 60 or float(seconds) >= 60:
                raise ValueError('Invalid transcript timestamp')
            times.append(int(hours) * 3600 + int(minutes) * 60 + float(seconds))
        if times[1] < times[0]:
            raise ValueError('Transcript segment ends before it starts')
        line['id'] = index
    return transcript


def run_command(command, workspace, log, timeout):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                               cwd=workspace, start_new_session=True)
    try:
        return_code = process.wait(timeout=timeout)
        if return_code:
            raise subprocess.CalledProcessError(return_code, command)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()


def run_batch(workspace, publish_root, model, language, threads, worker_command, timeout=3600, ffmpeg_command=None):
    os.umask(0o077)
    workspace = private_directory(workspace)
    with (workspace / 'runner.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('A runner is already active for this batch') from error
        return _run_batch(workspace, publish_root, model, language, threads, worker_command, timeout, ffmpeg_command)


def _run_batch(workspace, publish_root, model, language, threads, worker_command, timeout, ffmpeg_command):
    os.umask(0o077)
    if not isinstance(worker_command, list) or not worker_command or not all(isinstance(arg, str) and arg for arg in worker_command):
        raise ValueError('Worker command must be a nonempty argument list')
    if threads < 1 or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError('Threads and timeout must be positive')
    ffmpeg_command = ['ffmpeg'] if ffmpeg_command is None else ffmpeg_command
    if not isinstance(ffmpeg_command, list) or not ffmpeg_command or not all(isinstance(arg, str) and arg for arg in ffmpeg_command):
        raise ValueError('FFmpeg command must be a nonempty argument list')
    workspace = private_directory(workspace)
    batch_id = str(uuid.UUID(workspace.name))
    publish_root = private_directory(publish_root)
    with checked_path(workspace, 'input-manifest.json').open(encoding='utf-8') as source:
        manifest = json.load(source)
    if not isinstance(manifest, list) or not manifest:
        raise ValueError('Input manifest must contain files')
    inputs = []
    for entry in manifest:
        if (not isinstance(entry, dict) or not isinstance(entry.get('name'), str)
            or not isinstance(entry.get('path'), str)
            or not isinstance(entry.get('size'), int) or entry['size'] <= 0):
            raise ValueError('Invalid input manifest entry')
        name = entry['name']
        if (not name or Path(name).name != name or name.startswith('.')
                or '\\' in name or any(ord(character) < 32 for character in name)):
            raise ValueError('Input filenames must be plain, non-hidden filenames')
        path = checked_path(workspace, entry['path'])
        if path.parent != workspace / 'input' or path.stat().st_size != entry['size']:
            raise ValueError('Staged input is incomplete or not in the input directory')
        inputs.append(path)
    if len(set(inputs)) != len(inputs):
        raise ValueError('Duplicate manifest input')
    stems = [Path(entry['name']).stem for entry in manifest]
    if len(set(stems)) != len(stems):
        raise ValueError('Input filenames must have distinct stems to avoid output collisions')
    worker_model = model.removeprefix('whisper/')
    if model == 'nvidia/parakeet-tdt-0.6b-v3':
        worker_model = 'parakeet'
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', worker_model) or not re.fullmatch(r'[A-Za-z0-9-]+', language):
        raise ValueError('Invalid model or language')
    logs = private_directory(workspace / 'logs')
    progress_path = workspace / 'progress.json'
    completion_path = workspace / 'completion.json'
    if completion_path.exists():
        raise ValueError('Completion manifest already exists')
    attempt = uuid.uuid4().hex
    raw_output = private_directory(workspace / f'worker-{attempt}')
    worker_input = private_directory(workspace / f'worker-input-{attempt}')
    staging = private_directory(publish_root / f'.{batch_id}-{attempt}')
    published = []
    try:
        write_json(progress_path, {'state': 'running', 'completed_files': 0, 'total_files': len(inputs)})
        for entry, input_path in zip(manifest, inputs):
            os.link(input_path, worker_input / entry['name'])
        command = worker_command + [
            '--job_name', 'files', '--input_dir', str(worker_input),
            '-o', str(raw_output), '-m', worker_model, '--threads', str(threads),
            '--merge_speakers', '--transcriber_gui',
        ]
        if language != 'auto':
            command += ['--language', language]
        with (logs / 'worker.log').open('w', encoding='utf-8') as log:
            run_command(command, workspace, log, timeout)
        results = []
        for index, (entry, input_path) in enumerate(zip(manifest, inputs)):
            item_key = f"{Path(entry['name']).stem}_{worker_model}_{language}"
            item = private_directory(staging / item_key)
            data = private_directory(item / 'data')
            transcripts = private_directory(item / 'TRANSCRIPTIONS')
            prefix = f"{Path(entry['name']).stem}_{worker_model}"
            pattern = re.escape(prefix) + ('' if worker_model == 'parakeet' else r'_[a-z]{2,3}(?:-[A-Za-z]{2,4})?') + r'\.dote\.json'
            candidates = [path for path in raw_output.iterdir() if re.fullmatch(pattern, path.name)]
            if len(candidates) != 1:
                raise ValueError('Worker must produce exactly one unmerged transcript per input')
            transcript_path = checked_path(raw_output, candidates[0].name)
            transcript = read_transcript(transcript_path)
            write_json(data / 'edited_output.json', transcript)
            basename = transcript_path.name.removesuffix('.dote.json')
            for artifact in transcription_files(raw_output, basename):
                shutil.copyfile(artifact, transcripts / artifact.name)
            for name in ('files.zip', 'transcribe.log'):
                shutil.copyfile(checked_path(raw_output, name), transcripts / name)
            shutil.copyfile(logs / 'worker.log', transcripts / 'transcriber_output.txt')
            stored_name = entry['name']
            shutil.copyfile(input_path, data / stored_name)
            if input_path.suffix.lower() not in ('.mp3', '.wav'):
                with (logs / 'conversion.log').open('a', encoding='utf-8') as log:
                    run_command(ffmpeg_command + ['-nostdin', '-y', '-i', str(data / stored_name),
                                 str(data / 'converted_audio.mp3')], workspace, log, timeout)
            write_json(data / 'metadata.json', {
                'input_file_name': stored_name, 'original_file_name': entry['name'],
                'input_file_converted': input_path.suffix.lower() not in ('.mp3', '.wav'),
                'user_edited': False, 'model': worker_model, 'language': language,
            })
            results.append({'directory': item_key, 'name': entry['name']})
            write_json(progress_path, {'state': 'publishing', 'completed_files': index + 1, 'total_files': len(inputs)})
        completion = {'batch_id': batch_id, 'state': 'succeeded',
                      'model': model, 'language': language, 'results': results}
        with (publish_root / '.publish.lock').open('a') as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            for result in results:
                base = result['directory']
                name = base
                run_number = 2
                while (publish_root / name).exists() or (publish_root / name).is_symlink():
                    name = f'{base}_run{run_number}'
                    run_number += 1
                destination = publish_root / name
                (staging / base).rename(destination)
                published.append(destination)
                result['directory'] = name
            write_json(completion_path, completion)
        write_json(progress_path, {'state': 'succeeded', 'completed_files': len(inputs), 'total_files': len(inputs)})
        return completion
    except BaseException:
        for directory in published:
            shutil.rmtree(directory)
        completion_path.unlink(missing_ok=True)
        write_json(progress_path, {'state': 'failed', 'total_files': len(inputs)})
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(raw_output, ignore_errors=True)
        shutil.rmtree(worker_input, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(description='Run a staged transcription batch without Django or Celery.')
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--publish-root', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--language', default='auto')
    parser.add_argument('--threads', type=int, default=1)
    parser.add_argument('--timeout', type=float, default=3600)
    parser.add_argument('--worker-command', required=True, help='JSON argument list, including the worker executable')
    parser.add_argument('--ffmpeg-command', default='["ffmpeg"]', help='Trusted JSON argument list for media conversion')
    args = parser.parse_args()
    def terminate(signum, frame):
        raise InterruptedError('Runner was terminated')
    signal.signal(signal.SIGTERM, terminate)
    try:
        run_batch(args.workspace, args.publish_root, args.model, args.language, args.threads,
                  json.loads(args.worker_command), args.timeout, json.loads(args.ffmpeg_command))
    except (Exception, KeyboardInterrupt) as error:
        print(f'Batch failed: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())