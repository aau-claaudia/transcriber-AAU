import json
import re
import shutil
import uuid
import os
import sys
import subprocess
import fcntl
from pathlib import Path

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Transcription
from .private_storage import private_directory
from .hpc_files import validate_selection, open_entry, fingerprint


class ActiveTranscriptionError(Exception):
    pass


def stage_uploads(files, model, language, profile, metadata=None, existing_tokens=None):
    existing_tokens = [] if existing_tokens is None else existing_tokens
    if not isinstance(existing_tokens, list) or not all(isinstance(token, str) for token in existing_tokens):
        raise ValueError('Existing files must be a list of selection tokens')
    if model not in settings.TRANSCRIPTION_MODELS:
        raise ValueError('Select a supported transcription model')
    if language != 'auto' and not re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z]{2,4})?', language):
        raise ValueError('Invalid language code')
    if profile not in settings.RESOURCE_PROFILES:
        raise ValueError('Select a supported resource profile')
    if (not files and not existing_tokens) or len(files) + len(existing_tokens) > settings.MAX_UPLOAD_FILES:
        raise ValueError('Invalid number of uploaded files')
    selections = [validate_selection(token) for token in existing_tokens]
    names = [uploaded.name for uploaded in files] + [Path(selection['path']).name for selection in selections]
    if len(set(names)) != len(names):
        raise ValueError('Duplicate filenames in this batch')
    stems = [Path(name).stem for name in names]
    if len(set(stems)) != len(stems):
        raise ValueError('Input filenames must have distinct stems to avoid output collisions')
    if metadata is not None:
        if not isinstance(metadata, list) or len(metadata) != len(files):
            raise ValueError('File metadata must match the uploaded files')
        for uploaded, entry in zip(files, metadata):
            if not isinstance(entry, dict) or entry.get('name') != uploaded.name or entry.get('size') != uploaded.size:
                raise ValueError('File metadata does not match the uploaded files')
    for uploaded in files:
        if Path(uploaded.name).suffix.lower() not in settings.ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError('Unsupported audio/video file extension')
        if not 0 < uploaded.size <= settings.MAX_UPLOAD_FILE_BYTES:
            raise ValueError('File is empty or exceeds the upload size limit')
    for selection in selections:
        if not 0 < selection['fingerprint'][2] <= settings.MAX_UPLOAD_FILE_BYTES:
            raise ValueError('Selected file is empty or exceeds the size limit')
    total_size = sum(uploaded.size for uploaded in files) + sum(selection['fingerprint'][2] for selection in selections)
    if total_size > settings.MAX_UPLOAD_BATCH_BYTES:
        raise ValueError('Batch exceeds the upload size limit')
    active = Transcription.objects.filter(active_slot=1).first()
    if active:
        from .slurm import reconcile
        reconcile(active)
    try:
        with transaction.atomic():
            transcription = Transcription.objects.create(
                model=model, language=language, resource_profile=profile,
                resources=settings.RESOURCE_PROFILES[profile],
            )
    except IntegrityError as error:
        if Transcription.objects.filter(active_slot=1).exists():
            raise ActiveTranscriptionError('An active transcription already exists') from error
        raise

    workspace = Path(settings.JOBS_ROOT) / str(transcription.id)
    try:
        private_directory(settings.JOBS_ROOT)
        private_directory(workspace)
        input_directory = private_directory(workspace / 'input')
        private_directory(workspace / 'output')
        private_directory(workspace / 'logs')
        manifest = []
        for uploaded in files:
            stored_name = f'{uuid.uuid4().hex}{Path(uploaded.name).suffix.lower()}'
            destination = input_directory / stored_name
            written = 0
            with destination.open('xb') as output:
                destination.chmod(0o600)
                for chunk in uploaded.chunks():
                    written += len(chunk)
                    if written > uploaded.size or written > settings.MAX_UPLOAD_FILE_BYTES:
                        raise ValueError('Uploaded file exceeds its declared size')
                    output.write(chunk)
            if written != uploaded.size:
                raise ValueError('Incomplete uploaded file')
            manifest.append({'name': uploaded.name, 'size': written,
                             'path': f'input/{stored_name}', 'source': 'upload'})
        for selection in selections:
            stored_name = f"{uuid.uuid4().hex}{Path(selection['path']).suffix.lower()}"
            manifest.append({'name': Path(selection['path']).name, 'size': selection['fingerprint'][2],
                             'path': f'input/{stored_name}', 'source': 'hpc', 'selection': selection})
        manifest_path = workspace / 'input-manifest.json'
        with manifest_path.open('x') as output:
            manifest_path.chmod(0o600)
            json.dump(manifest, output)
        updated = Transcription.objects.filter(pk=transcription.id, state=Transcription.State.PREPARING).update(
            input_manifest=manifest,
            state=Transcription.State.PREPARING if selections else Transcription.State.STAGED,
            updated_at=timezone.now(),
        )
        if not updated:
            shutil.rmtree(workspace)
        elif selections:
            launch_preparation(transcription.id)
        transcription.refresh_from_db()
        if transcription.state == 'staged':
            from .slurm import schedule_ready
            transcription = schedule_ready(transcription)
        return transcription
    except Exception as error:
        shutil.rmtree(workspace, ignore_errors=True)
        Transcription.objects.filter(pk=transcription.id, state=Transcription.State.PREPARING).update(
            state=Transcription.State.FAILED, active_slot=None,
            failure_detail=('Upload validation failed' if isinstance(error, ValueError) else 'Unable to stage uploaded files'),
            updated_at=timezone.now(), finished_at=timezone.now(),
        )
        raise


def transcription_status(transcription):
    elapsed_seconds = None
    if transcription.slurm_started_at is not None:
        elapsed_seconds = max(0, ((transcription.finished_at or timezone.now())
                                 - transcription.slurm_started_at).total_seconds())
    states = {'succeeded': 'SUCCESS', 'failed': 'FAILURE', 'cancelled': 'CANCELLED'}
    messages = {
        'preparing': 'Preparing files from HPC storage',
        'staged': ('Files staged. Awaiting scheduler submission.' if settings.TRANSCRIBER_SLURM_ENABLED
               else 'Files staged. Scheduler integration is not available yet.'),
        'cancelled': 'Transcription cancelled',
    }
    return {
        'task_id': str(transcription.id),
        'state': states.get(transcription.state, 'PENDING'),
        'job_state': transcription.state,
        'status': transcription.failure_detail or messages.get(transcription.state, transcription.get_state_display()),
        'model': transcription.model, 'language': transcription.language,
        'resource_profile': transcription.resource_profile,
        'files': [{'name': entry['name'], 'size': entry['size'], 'source': entry['source']}
              for entry in transcription.input_manifest],
        'created_at': transcription.created_at.isoformat(),
        'slurm_job_id': transcription.slurm_job_id or None,
        'slurm_started_at': transcription.slurm_started_at.isoformat() if transcription.slurm_started_at else None,
        'estimated_duration_seconds': sum(entry['size'] for entry in transcription.input_manifest) / 1000000 * 60,
        'elapsed_seconds': elapsed_seconds,
    }


def launch_preparation(transcription_id):
    environment = os.environ.copy()
    environment['TRANSCRIBER_DATA_ROOT'] = str(settings.DATA_ROOT)
    environment['TRANSCRIBER_INPUT_ROOTS'] = json.dumps(settings.INPUT_ROOTS)
    environment['SECRET_KEY'] = settings.SECRET_KEY
    workspace = Path(settings.JOBS_ROOT) / str(transcription_id)
    with (workspace / 'logs/preparation.log').open('ab') as log:
        subprocess.Popen(
            [sys.executable, str(settings.BASE_DIR / 'manage.py'), 'prepare_inputs', str(transcription_id)],
            cwd=settings.BASE_DIR, env=environment, stdin=subprocess.DEVNULL,
            stdout=log, stderr=log, start_new_session=True, close_fds=True,
        )


def prepare_existing_inputs(transcription_id):
    transcription = Transcription.objects.get(pk=transcription_id)
    if transcription.state != Transcription.State.PREPARING or not transcription.input_manifest:
        return
    workspace = Path(settings.JOBS_ROOT) / str(transcription.id)
    with (workspace / 'preparation.lock').open('a') as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            for entry in transcription.input_manifest:
                if not Transcription.objects.filter(pk=transcription.id, state='preparing').exists():
                    return
                if entry['source'] != 'hpc':
                    if (workspace / entry['path']).stat().st_size != entry['size']:
                        raise ValueError('Staged upload is incomplete')
                    continue
                selection = entry['selection']
                destination = workspace / entry['path']
                temporary = destination.with_suffix(destination.suffix + '.part')
                written = 0
                with open_entry(selection['root'], selection['path']) as descriptor:
                    if fingerprint(os.fstat(descriptor)) != selection['fingerprint']:
                        raise ValueError('Source changed before preparation')
                    with os.fdopen(os.dup(descriptor), 'rb') as source, temporary.open('wb') as output:
                        temporary.chmod(0o600)
                        while chunk := source.read(1024 * 1024):
                            if not Transcription.objects.filter(pk=transcription.id, state='preparing').exists():
                                temporary.unlink(missing_ok=True)
                                return
                            written += len(chunk)
                            if written > entry['size']:
                                raise ValueError('Source changed while copying')
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if written != entry['size'] or fingerprint(os.fstat(descriptor)) != selection['fingerprint']:
                        raise ValueError('Source changed while copying')
                temporary.replace(destination)
            Transcription.objects.filter(pk=transcription.id, state='preparing').update(
                state=Transcription.State.STAGED, updated_at=timezone.now(),
            )
            transcription.refresh_from_db()
            from .slurm import schedule_ready
            schedule_ready(transcription)
        except Exception:
            for partial in (workspace / 'input').glob('*.part'):
                partial.unlink(missing_ok=True)
            Transcription.objects.filter(pk=transcription.id, state='preparing').update(
                state=Transcription.State.FAILED, active_slot=None,
                failure_detail='Unable to prepare selected files. Refresh the file browser and submit again.',
                updated_at=timezone.now(), finished_at=timezone.now(),
            )
            raise