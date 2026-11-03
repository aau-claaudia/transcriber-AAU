import os
import pwd
import json
import re
import shlex
import subprocess
from datetime import timezone as datetime_timezone
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .batch_runner import checked_path, transcription_files
from .models import Transcription


class SchedulerError(Exception):
    pass


def enabled():
    return settings.TRANSCRIBER_SLURM_ENABLED


def current_user():
    return pwd.getpwuid(os.getuid()).pw_name


def schedule_ready(record):
    try:
        return submit(record)
    except (ValueError, OSError, KeyError, TypeError):
        Transcription.objects.filter(pk=record.pk, state='staged').update(
            failure_detail='Scheduler configuration is invalid; contact the administrator',
        )
        record.refresh_from_db()
        return record


def call_slurm(arguments, script=None):
    try:
        result = subprocess.run(settings.SLURM_COMMAND_PREFIX + arguments, input=script,
                                text=True, capture_output=True, check=True,
                                timeout=settings.SLURM_RPC_TIMEOUT,
                                env={**os.environ, 'TZ': 'UTC', 'SLURM_TIME_FORMAT': 'standard'})
        return result.stdout
    except (OSError, subprocess.SubprocessError) as error:
        raise SchedulerError('Scheduler request failed; reconciliation will retry') from error


def job_name(record):
    return f'transcriber-{record.id}'


def options(record):
    resources = record.resources
    allowed = {'label', 'memory_gb', 'memory_mb', 'partition', 'account', 'qos', 'cpus', 'time_minutes', 'gres', 'constraint', 'nodelist'}
    if not isinstance(resources, dict) or set(resources) - allowed:
        raise ValueError('Unsupported resource profile options')
    arguments = []
    for name in ('partition', 'account', 'qos', 'gres', 'constraint', 'nodelist'):
        value = resources.get(name)
        if value is not None:
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.:,\[\]-]+', value):
                raise ValueError('Invalid scheduler resource option')
            arguments.append(f'--{name}={value}')
    for name, flag, default in [('cpus', 'cpus-per-task', 1), ('memory_gb', 'mem', 16),
                                ('time_minutes', 'time', 30)]:
        if name == 'memory_gb' and 'memory_mb' in resources:
            value = resources['memory_mb']
            if type(value) is not int or value < 1:
                raise ValueError('Scheduler memory must be a positive integer')
            arguments.append(f'--mem={value}M')
            continue
        value = resources.get(name, default)
        if type(value) is not int or value < 1:
            raise ValueError('Scheduler resource limits must be positive integers')
        arguments.append(f'--{flag}={value}{"G" if flag == "mem" else ""}')
    return arguments


def submission(record):
    workspace = Path(settings.JOBS_ROOT) / str(record.id)
    checked_path(workspace.resolve(), 'input-manifest.json')
    worker = settings.TRANSCRIBER_WORKER_COMMAND
    if not isinstance(worker, list) or not worker or not all(isinstance(arg, str) and arg for arg in worker):
        raise ValueError('Configure a trusted worker command argument list')
    command = [settings.TRANSCRIBER_COMPUTE_PYTHON, str(settings.TRANSCRIBER_RUNNER_PATH),
               '--workspace', str(workspace), '--publish-root', str(settings.MEDIA_ROOT),
               '--model', record.model, '--language', record.language,
               '--threads', str(record.resources.get('cpus', 1)),
               '--timeout', str(record.resources.get('time_minutes', 30) * 60),
               '--worker-command', json.dumps(worker),
               '--ffmpeg-command', json.dumps(settings.TRANSCRIBER_FFMPEG_COMMAND)]
    script = '#!/bin/bash\nset -euo pipefail\numask 077\nexec ' + shlex.join(command) + '\n'
    arguments = ['sbatch', '--parsable', '--job-name=' + job_name(record), '--nodes=1',
                 '--ntasks=1', '--chdir=' + str(workspace),
                 '--output=' + str(workspace / 'logs/slurm-%j.log'),
                 '--error=' + str(workspace / 'logs/slurm-%j.log')] + options(record)
    return arguments, script


def submit(record):
    if not enabled() or record.state != 'staged':
        return record
    arguments, script = submission(record)
    if not Transcription.objects.filter(pk=record.pk, state='staged').update(
        state='submitting', updated_at=timezone.now(), failure_detail='',
    ):
        record.refresh_from_db()
        return record
    try:
        response = call_slurm(arguments, script).strip()
        match = re.fullmatch(r'(\d+)(?:;[A-Za-z0-9_.-]+)?', response)
        if not match:
            raise SchedulerError('Submission response was unclear; reconciliation will search for the job')
        Transcription.objects.filter(pk=record.pk, state__in=['submitting', 'cancelling']).update(
            slurm_job_id=match[1], updated_at=timezone.now(), failure_detail='',
        )
        Transcription.objects.filter(pk=record.pk, state='submitting').update(state='queued')
    except SchedulerError as error:
        Transcription.objects.filter(pk=record.pk, active_slot=1).update(failure_detail=str(error))
    record.refresh_from_db()
    return record


def query(record):
    username = current_user()
    filter_args = ['--jobs', record.slurm_job_id] if record.slurm_job_id else ['--name', job_name(record)]
    try:
        live = call_slurm(['squeue', '--noheader', '--user', username, '--format=%i|%j|%T|%S'] + filter_args)
    except SchedulerError as error:
        cause = error.__cause__
        if (record.slurm_job_id and isinstance(cause, subprocess.CalledProcessError)
                and 'Invalid job id specified' in (cause.stderr or '')):
            live = ''
        else:
            raise
    rows = []
    for line in live.splitlines():
        fields = line.strip().split('|')
        if len(fields) >= 3 and fields[1] == job_name(record) and fields[0].isdigit():
            rows.append((fields[0], fields[2], '', fields[3] if len(fields) > 3 else ''))
    if rows:
        return rows
    filter_args = ['--jobs', record.slurm_job_id] if record.slurm_job_id else ['--name', job_name(record)]
    history = call_slurm(['sacct', '--noheader', '--parsable2', '--allocations', '--user', username,
                         '--starttime', record.created_at.strftime('%Y-%m-%d'),
                         '--format=JobIDRaw,JobName%80,State,ExitCode,Start'] + filter_args)
    for line in history.splitlines():
        fields = line.strip().split('|')
        if len(fields) >= 4 and fields[0].isdigit() and fields[1] == job_name(record):
            rows.append((fields[0], fields[2].split()[0].rstrip('+'), fields[3],
                         fields[4] if len(fields) > 4 else ''))
    return rows


def complete_results(record):
    media = Path(settings.MEDIA_ROOT).resolve()
    workspace = (Path(settings.JOBS_ROOT) / str(record.id)).resolve()
    path = checked_path(workspace, 'completion.json')
    with path.open(encoding='utf-8') as source:
        completion = json.load(source)
    if (completion.get('state') != 'succeeded'
            or completion.get('batch_id') != str(record.id)
            or completion.get('model') != record.model or completion.get('language') != record.language):
        raise ValueError('Invalid completion manifest')
    results = completion.get('results')
    if not isinstance(results, list) or len(results) != len(record.input_manifest) or not results:
        raise ValueError('Incomplete published results')
    directories = set()
    for index, item in enumerate(results):
        if not isinstance(item, dict):
            raise ValueError('Invalid result directory')
        directory = item.get('directory')
        if (not isinstance(directory, str) or not directory or Path(directory).name != directory
                or directory.startswith('.') or directory in directories
                or item.get('name') != record.input_manifest[index]['name']):
            raise ValueError('Invalid result directory')
        directories.add(directory)
        edited = checked_path(media, f'{directory}/data/edited_output.json')
        with edited.open(encoding='utf-8') as source:
            transcript = json.load(source)
        if not isinstance(transcript, dict) or not isinstance(transcript.get('lines'), list):
            raise ValueError('Invalid published transcript')
        metadata_path = checked_path(media, f'{directory}/data/metadata.json')
        with metadata_path.open(encoding='utf-8') as source:
            metadata = json.load(source)
        if metadata.get('original_file_name') != item['name']:
            raise ValueError('Published input does not match the manifest')
        checked_path(media, f"{directory}/data/{metadata['input_file_name']}")
        if metadata.get('input_file_converted'):
            checked_path(media, f'{directory}/data/converted_audio.mp3')
        transcript_directory = checked_path(media, f'{directory}/TRANSCRIPTIONS/files.zip').parent
        candidates = [path for path in transcript_directory.iterdir()
                      if path.name.endswith('.dote.json') and not path.name.endswith('_merged.dote.json')]
        if len(candidates) != 1:
            raise ValueError('Expected one original DOTE transcript')
        transcription_files(transcript_directory, candidates[0].name.removesuffix('.dote.json'))
        for name in ('files.zip', 'transcribe.log', 'transcriber_output.txt'):
            checked_path(media, f'{directory}/TRANSCRIPTIONS/{name}')
    return completion


def reconcile(record):
    if not enabled() or record.active_slot is None or record.state in ('preparing',):
        return record
    if record.state == 'staged':
        return schedule_ready(record)
    try:
        rows = query(record)
        if len(rows) > 1:
            raise SchedulerError('Multiple matching jobs found; operator review required')
        if not rows:
            raise SchedulerError('Waiting for scheduler records; the batch will not be resubmitted')
        identifier, state, exit_code, start_time = rows[0]
        if record.slurm_job_id and identifier != record.slurm_job_id:
            raise SchedulerError('Scheduler identity mismatch')
        record.refresh_from_db()
        if record.active_slot is None:
            return record
        updates = {'slurm_job_id': identifier, 'updated_at': timezone.now(), 'failure_detail': ''}
        if start_time and state not in {'PENDING', 'CONFIGURING', 'REQUEUED', 'REQUEUE_FED', 'REQUEUE_HOLD'}:
            try:
                started_at = parse_datetime(start_time)
            except ValueError:
                started_at = None
            if started_at is not None:
                if timezone.is_naive(started_at):
                    started_at = timezone.make_aware(started_at, datetime_timezone.utc)
                updates['slurm_started_at'] = started_at
        terminal = False
        if state == 'COMPLETED' and exit_code == '0:0':
            try:
                complete_results(record)
            except (ValueError, OSError, KeyError, TypeError) as error:
                if record.scheduler_terminal_seen_at is None:
                    Transcription.objects.filter(pk=record.pk, scheduler_terminal_seen_at__isnull=True).update(
                        scheduler_terminal_seen_at=timezone.now())
                    raise SchedulerError('Job completed; waiting for valid published results') from error
                if (timezone.now() - record.scheduler_terminal_seen_at).total_seconds() < settings.SLURM_RESULT_GRACE_SECONDS:
                    raise SchedulerError('Job completed; waiting for valid published results') from error
                updates.update(state='failed', failure_detail='Job completed without valid published results')
                terminal = True
            else:
                updates['state'] = 'succeeded'
                terminal = True
        elif state.startswith('CANCELLED'):
            updates['state'] = 'cancelled'
            terminal = True
        elif state in {'FAILED', 'TIMEOUT', 'OUT_OF_MEMORY', 'NODE_FAIL', 'BOOT_FAIL', 'DEADLINE', 'PREEMPTED', 'REVOKED'} or state == 'COMPLETED':
            updates.update(state='failed', failure_detail=f'Slurm job ended with {state} ({exit_code})')
            terminal = True
        elif record.state != 'cancelling':
            updates['state'] = 'running' if state in {'RUNNING', 'COMPLETING', 'SUSPENDED'} else 'queued'
        if record.state == 'cancelling' and not terminal:
            call_slurm(['scancel', '--user', current_user(), identifier])
        if terminal:
            updates.update(active_slot=None, finished_at=timezone.now())
        Transcription.objects.filter(pk=record.pk, active_slot=1, state=record.state).update(**updates)
    except SchedulerError as error:
        Transcription.objects.filter(pk=record.pk, active_slot=1).update(failure_detail=str(error))
    record.refresh_from_db()
    return record


def cancel(record):
    if record.active_slot is None:
        return record
    if record.state in ('preparing', 'staged'):
        Transcription.objects.filter(pk=record.pk, state__in=['preparing', 'staged']).update(
            state='cancelled', active_slot=None, finished_at=timezone.now(), updated_at=timezone.now(),
        )
    else:
        Transcription.objects.filter(pk=record.pk, active_slot=1).update(state='cancelling', updated_at=timezone.now())
    record.refresh_from_db()
    return reconcile(record)