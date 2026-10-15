from django.conf import settings
from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse, HttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt, ensure_csrf_cookie
from django.views.decorators.http import require_POST, require_GET
from django.utils import timezone as django_timezone
from transcriber.models import Transcription
import os
import json
from urllib.parse import quote
from django.utils.http import content_disposition_header
from datetime import datetime, timezone
from .staging import stage_uploads, transcription_status, ActiveTranscriptionError
from .hpc_files import list_directory, root_options
from .slurm import reconcile, cancel
from .utils import convert_to_mp3
import logging
from transcriber.exporter import export

logger = logging.getLogger(__name__)

@ensure_csrf_cookie
def index(request):
    return render(request, 'frontend/build/index.html', {
        'app_prefix': settings.APP_PREFIX,
        'app_base': settings.APP_PREFIX + '/',
        'csrf_cookie_name': settings.CSRF_COOKIE_NAME,
    })

@require_POST
def upload_file(request):
    """
    POST /upload/
    Multipart form data:
      - files            : one or more uploaded audio/video files
            - file_meta_data   : optional JSON array of expected names and sizes
      - model            : whisper model name
      - language         : language code
            - resource_profile : configured resource profile identifier
            - existing_files   : signed HPC file-selection tokens
    """
    try:
        if request.POST.get('transcribe_and_shutdown') == 'true':
            raise ValueError('Server shutdown is not supported in OnDemand')
        metadata = request.POST.get('file_meta_data')
        transcription = stage_uploads(
            request.FILES.getlist('files'), request.POST.get('model', ''),
            request.POST.get('language', 'auto'), request.POST.get('resource_profile', 'cpu-test'),
            json.loads(metadata) if metadata is not None else None,
            existing_tokens=json.loads(request.POST.get('existing_files', '[]')),
        )
    except ActiveTranscriptionError as error:
        return JsonResponse({'error': str(error)}, status=409)
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    except OSError:
        logger.exception('Upload staging failed')
        return JsonResponse({'error': 'Unable to store uploaded files'}, status=503)
    return JsonResponse(transcription_status(transcription), status=201)


@csrf_exempt
def link_files(request):
    return JsonResponse({'error': 'Legacy symlink selection is disabled'}, status=410)

@ensure_csrf_cookie
def get_initialization_data(request):
    active = Transcription.objects.filter(active_slot=1).first()
    if active:
        active = reconcile(active)
        if active.active_slot is None:
            active = None
    results = prepare_results(request)
    default_profile = next(iter(settings.RESOURCE_PROFILES.values()))
    return JsonResponse({
        'file_list': [], 'mounted_folder': False,
        'available_memory': default_profile['memory_gb'],
        'resource_profiles': settings.RESOURCE_PROFILES,
        'default_model': settings.TRANSCRIBER_DEFAULT_MODEL,
        'input_roots': root_options(),
        'active_transcription': transcription_status(active) if active else None,
        'transcriptions': results, 'results': results,
    })


def get_active_transcription(request):
    active = Transcription.objects.filter(active_slot=1).first()
    if active:
        active = reconcile(active)
        if active.active_slot is None:
            active = None
    return JsonResponse({'active_transcription': transcription_status(active) if active else None})


@require_GET
def browse_hpc_files(request):
    try:
        listing = list_directory(request.GET.get('root', ''), request.GET.get('path', ''),
                                 int(request.GET.get('offset', 0)))
    except ValueError as error:
        return JsonResponse({'error': str(error)}, status=400)
    except OSError:
        return JsonResponse({'error': 'Directory is not accessible'}, status=403)
    return JsonResponse(listing)

@csrf_exempt
def remove_link(request):
    return JsonResponse({'error': 'Legacy symlink selection is disabled'}, status=410)

def poll_transcription_status(request, task_id):
    transcription = get_object_or_404(Transcription, pk=task_id)
    transcription = reconcile(transcription)
    response = transcription_status(transcription)
    if transcription.state == Transcription.State.SUCCEEDED:
        response['result'] = prepare_results(request)
    return JsonResponse(response)

def get_completed_transcriptions(request):
    response = {}
    responses = prepare_results(request)
    response['result'] = responses
    return JsonResponse(response)

def _metadata_input_converted(meta_data):
    """Return conversion flag from metadata"""
    value = meta_data.get('input_file_converted')
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return False

def _get_user_edited_flag(meta_data):
    """Return user edited flag from metadata"""
    value = meta_data.get('user_edited')
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return False

def _ensure_user_edited_metadata(dir_name):
    """
    Ensure metadata.json for the transcription dir has 'user_edited': True.
    Only writes to disk if 'user_edited' is not already True (first edit only).
    """
    if not dir_name:
        return
    data_dir = os.path.join(settings.MEDIA_ROOT, dir_name, 'data')
    metadata_path = os.path.join(data_dir, 'metadata.json')
    meta = {}
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                meta = json.load(f)
        except Exception as e:
            logger.error(f"_ensure_user_edited_metadata: failed to read metadata.json in '{dir_name}': {e}")
            meta = {}

    if not _get_user_edited_flag(meta):
        meta['user_edited'] = True
        try:
            os.makedirs(data_dir, exist_ok=True)
            with open(metadata_path, 'w') as f:
                json.dump(meta, f, indent=2)
            logger.info(f"Updated user_edited to True for '{dir_name}'")
        except Exception as e:
            logger.error(f"_ensure_user_edited_metadata: failed to write metadata.json for '{dir_name}': {e}")

def _metadata_input_file_name(meta_data):
    value = meta_data.get('input_file_name')
    return value.strip() if isinstance(value, str) else ''

def _build_media_absolute_url(request, relative_path):
    media_prefix = settings.MEDIA_URL if settings.MEDIA_URL.endswith('/') else f"{settings.MEDIA_URL}/"
    rel = relative_path.lstrip('/')
    return request.build_absolute_uri(f"{media_prefix}{quote(rel)}")

def _infer_input_file_relative_path(dir_name, meta_data):
    if _metadata_input_converted(meta_data):
        return f"{dir_name}/data/converted_audio.mp3"

    input_file_name = _metadata_input_file_name(meta_data)
    if input_file_name:
        return f"{dir_name}/data/{input_file_name}"
    return ''

def prepare_results(request):
    responses = []

    if os.path.isdir(settings.MEDIA_ROOT):
        # avoid scanning folders in "old" transcriber-gui data structure
        exclude_dirs = {'UPLOADS', 'COMPLETED', 'TRANSCRIPTIONS', 'TRANSCRIPTIONS_TEMP'}
        candidate_dirs = []

        for dir_name in os.listdir(settings.MEDIA_ROOT):
            if dir_name in exclude_dirs or dir_name.startswith('.'):
                continue
            dir_path = os.path.join(settings.MEDIA_ROOT, dir_name)
            if not os.path.isdir(dir_path):
                continue

            # Include first-level folders under MEDIA_ROOT.
            candidate_dirs.append((dir_name, dir_path))

        for dir_name, dir_path in candidate_dirs:

            # Check if a TRANSCRIPTIONS folder exists within this directory
            trans_dir = os.path.join(dir_path, 'TRANSCRIPTIONS')
            if os.path.isdir(trans_dir):
                # Read metadata.json if it exists
                metadata_path = os.path.join(dir_path, 'data', 'metadata.json')
                input_file_url = None
                user_edited = False
                meta_data = {}
                edit_file_url = _build_media_absolute_url(request, f"{dir_name}/data/edited_output.json")
                if os.path.exists(metadata_path):
                    try:
                        with open(metadata_path, 'r') as f:
                            meta_data = json.load(f)
                            inferred_input_relative = _infer_input_file_relative_path(dir_name, meta_data)
                            if inferred_input_relative:
                                input_file_url = _build_media_absolute_url(request, inferred_input_relative)
                            user_edited = _get_user_edited_flag(meta_data)
                    except Exception as e:
                        logger.error(f"Error reading metadata.json in {dir_name}: {e}")

                # Fallback to scanning data/ if metadata was missing/incomplete
                if not input_file_url:
                    completed_dir = os.path.join(dir_path, 'data')
                    if os.path.isdir(completed_dir):
                        completed_files = [f for f in os.listdir(completed_dir) if (os.path.isfile(os.path.join(completed_dir, f)) and f.lower().endswith((".mp3", ".wav")))]
                        if completed_files:
                            input_file_url = _build_media_absolute_url(request, f"{dir_name}/data/{completed_files[0]}")

                for filename in os.listdir(trans_dir):
                    file_path = os.path.join(trans_dir, filename)
                    if os.path.isfile(file_path):
                        try:
                            created_at = os.path.getmtime(file_path)
                        except OSError:
                            created_at = 0.0
                        file_url = _build_media_absolute_url(request, f"{dir_name}/TRANSCRIPTIONS/{filename}")
                        responses.append({
                            'file_name': filename,
                            'file_url': file_url,
                            'created_at': created_at,
                            'input_file_url': input_file_url,
                            'dir_name': dir_name,
                            'original_file_name': meta_data.get('original_file_name', ''),
                            'model': meta_data.get('model', ''),
                            'language': meta_data.get('language', ''),
                            'edit_file_url': edit_file_url,
                            'user_edited': user_edited
                        })

    responses.sort(key=lambda x: x['file_name'])
    return responses

@require_POST
def stop_transcription_task(request, task_id):
    transcription = get_object_or_404(Transcription, pk=task_id)
    if transcription.state == 'running' and not transcription.slurm_job_id:
        return JsonResponse({'error': 'This job cannot be cancelled by the staging backend'}, status=409)
    transcription = cancel(transcription)
    return JsonResponse(transcription_status(transcription))

def serve_file(request, path):
    base_dir = settings.MEDIA_ROOT

    # Construct the full file path
    file_path = os.path.join(base_dir, path)
    # Check if the file exists
    if not os.path.exists(file_path):
        raise Http404("File not found")

    file_size = os.path.getsize(file_path)
    content_type = _guess_content_type(file_path)

    # Handle HTTP Range requests — required by browsers for audio/video seeking
    range_header = request.META.get('HTTP_RANGE', '').strip()
    if range_header and range_header.startswith('bytes='):
        try:
            # Send back a chunk of the audio file, the browser will automatically request more data as needed
            chunk_size = 256 * 1024  # 256 KB
            range_spec = range_header[6:]  # strip 'bytes='
            start_str, _, end_str = range_spec.partition('-')
            start = int(start_str) if start_str else 0
            if end_str:
                end = min(int(end_str), file_size - 1)
            else:
                # Open-ended request: cap how much we serve per response
                end = min(start + chunk_size - 1, file_size - 1)
            if start > end or start < 0:
                response = HttpResponse(status=416)
                response['Content-Range'] = f'bytes */{file_size}'
                return response
            length = end - start + 1
            with open(file_path, 'rb') as f:
                f.seek(start)
                data = f.read(length)
            response = HttpResponse(data, status=206, content_type=content_type)
            response['Content-Range'] = f'bytes {start}-{end}/{file_size}'
            response['Content-Length'] = str(length)
            response['Accept-Ranges'] = 'bytes'
            return response
        except (ValueError, IOError):
            pass  # fall through to full response on any parse error

    # Full file response (also advertises range support)
    with open(file_path, 'rb') as f:
        response = HttpResponse(f.read(), content_type=content_type)
    response['Content-Length'] = str(file_size)
    response['Accept-Ranges'] = 'bytes'
    response['Content-Disposition'] = content_disposition_header(
        os.path.basename(os.path.dirname(file_path)) == 'TRANSCRIPTIONS',
        os.path.basename(file_path),
    )
    return response

def export_file(request):
    """
    GET /export-file/?dir_name=<str>&target=<edited_output|notes>&format=<json|txt|docx>
    Handles request to download specified export file (edited_output.json or notes.json).
    Returns file as an attachment response.
    """
    dir_name = request.GET.get('dir_name', '').strip()
    target = request.GET.get('target', 'edited_output').strip()
    export_format = request.GET.get('format', 'json').strip().lower()
    merged_format = request.GET.get('merged', 'off').strip().lower()
    merged = False
    if merged_format == "on":
        merged = True

    if not dir_name:
        return JsonResponse({'error': 'dir_name parameter is required'}, status=400)

    # Determine target file path based on target parameter
    target_filename = 'notes.json' if target == 'notes' else 'edited_output.json'
    target_file_path = os.path.join(settings.MEDIA_ROOT, dir_name, 'data', target_filename)
    # Call export module
    file_path = export(dir_name, target_file_path, target, export_format, merged)
    if not os.path.exists(file_path):
        logger.error(f"Export file {file_path} not found for directory '{dir_name}'.")
        return JsonResponse({'error': 'There was an error generating the export file.'}, status=400)

    download_name = f"{dir_name}_{target}{'_merged' if merged else ''}.{export_format if export_format in ['json', 'txt', 'docx'] else 'json'}"

    try:
        with open(file_path, 'rb') as f:
            file_data = f.read()

        content_type = 'application/json'
        if export_format == 'txt':
            content_type = 'text/plain; charset=utf-8'
        elif export_format == 'docx':
            content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

        response = HttpResponse(file_data, content_type=content_type)
        response['Content-Length'] = str(len(file_data))
        response['Content-Disposition'] = f'attachment; filename="{download_name}"'
        return response
    except Exception as e:
        logger.error(f"export_file: failed to read '{file_path}': {e}")
        return JsonResponse({'error': 'Could not process export file'}, status=500)


def _guess_content_type(file_path):
    """Return a suitable MIME type for common audio/video files."""
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
    }
    return mime_map.get(ext, 'application/octet-stream')

def validate_file_size(actual_file_size, file_name, meta_data_list):
    size = get_size_by_name(meta_data_list, file_name)
    if size is not None:
        if size != actual_file_size :
            return False
    else:
        # the user must have uploaded the file more than once, and it will be post fixed by django with _xyz.
        # file already checked
        return True
    return True

def get_size_by_name(dict_list, file_name):
    for item in dict_list:
        if item.get('name') == file_name.removeprefix('UPLOADS/INPUT/'):
            return item.get('size')
    return None

def has_subdirectories(directory_path):
    # Iterate through the entries in the directory
    for entry in os.scandir(directory_path):
        # Check if the entry is a directory
        if entry.is_dir() and entry.name != 'UPLOADS':
            return True
    return False

def clean_model_name(model_name):
    # Clean parakeet model name
    if "parakeet" in model_name:
        return "parakeet"

    # Handle prefix removal from whisper model names
    prefix_to_remove = "whisper/"
    if model_name.startswith(prefix_to_remove):
        return model_name[len(prefix_to_remove):]

    return model_name

@csrf_exempt
def convert_audio(request):
    """
    POST endpoint: convert the input audio/video file for a transcription to .mp3.
    Called when editing notes and the input file format is unsupported.
    Expected JSON body:
        { "dir_name": "<transcription dir>" }
    Returns:
        { "status": "converted"|"already_converted"|"unchanged", "input_file_url": "<absolute url>" }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    dir_name = body.get('dir_name', '').strip()
    input_file_url = body.get('input_file_url', '').strip()

    if not dir_name:
        return JsonResponse({'error': 'dir_name is required'}, status=400)

    data_dir = os.path.join(settings.MEDIA_ROOT, dir_name, 'data')
    os.makedirs(data_dir, exist_ok=True)
    metadata_path = os.path.join(data_dir, 'metadata.json')

    meta = {}
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                meta = json.load(f)
        except Exception as e:
            logger.error(f"convert_audio: failed to read metadata.json for '{dir_name}': {e}")
            return JsonResponse({'error': 'Could not read metadata.json'}, status=500)

    input_file_name = _metadata_input_file_name(meta)

    # Determine output path: <MEDIA_ROOT>/<dir_name>/data/converted_audio.mp3
    output_fs_path = os.path.join(data_dir, 'converted_audio.mp3')
    output_media_rel = f"{dir_name}/data/converted_audio.mp3"
    output_abs_url = _build_media_absolute_url(request, output_media_rel)

    # Idempotency: if already converted, skip ffmpeg
    if os.path.exists(output_fs_path):
        logger.info(f"convert_audio: already converted for '{dir_name}', returning cached path.")
        try:
            meta['input_file_converted'] = True
            meta.pop('input_file_converted:', None)
            with open(metadata_path, 'w') as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            logger.error(f"convert_audio: failed to normalize metadata.json for '{dir_name}': {e}")
        return JsonResponse({'status': 'already_converted', 'input_file_url': output_abs_url})

    # Resolve input path from metadata first.
    input_fs_path = ''
    if input_file_name:
        candidate = os.path.join(settings.MEDIA_ROOT, dir_name, 'data', input_file_name)
        if os.path.exists(candidate):
            input_fs_path = candidate

    # Fallback: use first file in data/ when metadata is incomplete.
    if not input_fs_path:
        logger.warning(f"convert_audio: falling back to reading first file in data directory.")
        completed_dir = os.path.join(settings.MEDIA_ROOT, dir_name, 'data')
        if os.path.isdir(completed_dir):
            completed_files = [f for f in os.listdir(completed_dir) if (os.path.isfile(os.path.join(completed_dir, f)) and f.lower().endswith(("mp3", ".wav")))]
            if completed_files:
                input_file_name = input_file_name or completed_files[0]
                input_fs_path = os.path.join(completed_dir, completed_files[0])

    if not input_fs_path or not os.path.exists(input_fs_path):
        logger.warning(f"convert_audio: input file not found for '{dir_name}'")
        return JsonResponse({'status': 'unchanged', 'input_file_url': input_file_url})

    # Run conversion
    success, _ = convert_to_mp3(input_fs_path, output_fs_path)

    if not success:
        logger.warning(f"convert_audio: ffmpeg conversion failed for '{dir_name}'")
        return JsonResponse({'status': 'unchanged', 'input_file_url': input_file_url})

    # Update metadata.json with conversion flag only.
    try:
        if input_file_name:
            meta['input_file_name'] = input_file_name
        meta['input_file_converted'] = True
        with open(metadata_path, 'w') as f:
            json.dump(meta, f, indent=2)
        logger.info(f"convert_audio: updated metadata.json for '{dir_name}'")
    except Exception as e:
        logger.error(f"convert_audio: failed to update metadata.json for '{dir_name}': {e}")

    return JsonResponse({'status': 'converted', 'input_file_url': output_abs_url})

@csrf_exempt
def edit_transcription_segment(request):
    """
    POST endpoint: update segment text and speaker
    Called when editing notes for updating the edited output file
    Expected JSON body:
        { "dir_name": "<transcription dir>", "payload": "<update object>" }
    Returns:
        { status, type, dirName, editFileUrl }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    dir_name = str(body.get('dir_name', '')).strip()
    payload = body.get('payload')

    if not dir_name:
        return JsonResponse({'error': 'dir_name is required'}, status=400)
    if not isinstance(payload, dict):
        return JsonResponse({'error': 'payload must be an object'}, status=400)

    data_dir = os.path.join(settings.MEDIA_ROOT, dir_name, 'data')
    edit_file_path = os.path.join(data_dir, 'edited_output.json')
    edit_file_url = _build_media_absolute_url(request, f"{dir_name}/data/edited_output.json")

    if not os.path.exists(edit_file_path):
        return JsonResponse({'error': 'Target edit file not found'}, status=404)

    try:
        with open(edit_file_path, 'r') as f:
            edited_output = json.load(f)
    except Exception as e:
        logger.error(f"edit_transcription_segment: failed to read edit file '{edit_file_path}': {e}")
        return JsonResponse({'error': 'Could not read target edit file'}, status=500)

    lines = edited_output.get('lines')
    if not isinstance(lines, list):
        return JsonResponse({'error': "Target edit file format invalid (missing 'lines' array)"}, status=400)

    edit_type = payload.get('type')

    if edit_type == 'text_edit':
        segment_id = payload.get('segmentId')
        new_text = payload.get('newText')

        if not isinstance(segment_id, int) or segment_id < 0 or segment_id >= len(lines):
            return JsonResponse({'error': 'Invalid segmentId for text_edit'}, status=400)
        if not isinstance(new_text, str):
            return JsonResponse({'error': 'newText must be a string'}, status=400)

        if not isinstance(lines[segment_id], dict):
            return JsonResponse({'error': 'Segment entry has invalid structure'}, status=400)

        lines[segment_id]['text'] = new_text

    elif edit_type == 'speaker_edit':
        old_name = payload.get('oldName')
        new_name = payload.get('newName')
        update_all = payload.get('updateAll')
        segment_id = payload.get('segmentId')

        if not isinstance(old_name, str) or not isinstance(new_name, str):
            return JsonResponse({'error': 'oldName and newName must be strings'}, status=400)
        if not isinstance(update_all, bool):
            return JsonResponse({'error': 'updateAll must be a boolean'}, status=400)

        updates = 0
        if update_all:
            for line in lines:
                if isinstance(line, dict) and line.get('speakerDesignation') == old_name:
                    line['speakerDesignation'] = new_name
                    updates += 1
        else:
            if not isinstance(segment_id, int) or segment_id < 0 or segment_id >= len(lines):
                return JsonResponse({'error': 'Invalid segmentId for speaker_edit'}, status=400)
            if not isinstance(lines[segment_id], dict):
                return JsonResponse({'error': 'Segment entry has invalid structure'}, status=400)

            lines[segment_id]['speakerDesignation'] = new_name
            updates = 1

        if updates == 0:
            logger.info(
                f"edit_transcription_segment: speaker_edit made no changes for dir='{dir_name}', "
                f"old_name='{old_name}', update_all={update_all}"
            )
    else:
        return JsonResponse({'error': 'Unsupported payload type'}, status=400)

    try:
        with open(edit_file_path, 'w') as f:
            json.dump(edited_output, f, indent=2)
        _ensure_user_edited_metadata(dir_name)
    except Exception as e:
        logger.error(f"edit_transcription_segment: failed to write edit file '{edit_file_path}': {e}")
        return JsonResponse({'error': 'Failed to write target edit file'}, status=500)

    return JsonResponse({
        'status': 'ok',
        'type': edit_type,
        'dir_name': dir_name,
        'edit_file_url': edit_file_url
    })

def _read_notes_file(notes_path):
    """Return the parsed notes dict, or a blank one if the file doesn't exist."""
    if not os.path.exists(notes_path):
        return {'notes': []}
    try:
        with open(notes_path, 'r') as f:
            return json.load(f)
    except Exception:
        return {'notes': []}


def _write_notes_file(notes_path, data):
    """Write the notes dict back to disk with pretty formatting."""
    with open(notes_path, 'w') as f:
        json.dump(data, f, indent=2)


def get_notes(request):
    """
    GET /get-notes/?dir_name=<str>
    Returns all notes for the transcription, sorted by date ascending.
    Response: { "notes": [ { "id", "date", "note" }, … ] }
    """
    dir_name = request.GET.get('dir_name', '').strip()
    if not dir_name:
        return JsonResponse({'error': 'dir_name query parameter is required'}, status=400)

    notes_path = os.path.join(settings.MEDIA_ROOT, dir_name, 'data', 'notes.json')
    data = _read_notes_file(notes_path)
    notes = data.get('notes', [])

    # Sort ascending by date (ISO strings sort correctly lexicographically)
    notes_sorted = sorted(notes, key=lambda n: n.get('date', ''))
    return JsonResponse({'notes': notes_sorted})


@csrf_exempt
def save_note(request):
    """
    POST /save-note/
    Body: { "dir_name": "<str>", "note": "<str>" }
    Creates <MEDIA_ROOT>/<dir_name>/data/notes.json if it does not exist.
    Appends a new note object with an auto-incremented id and an ISO-8601 UTC date.
    Response: { "status": "ok", "note": { "id": <int>, "date": "<iso>", "note": "<str>" } }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    dir_name = str(body.get('dir_name', '')).strip()
    note_text = body.get('note')

    if not dir_name:
        return JsonResponse({'error': 'dir_name is required'}, status=400)
    if not isinstance(note_text, str) or not note_text.strip():
        return JsonResponse({'error': 'note must be a non-empty string'}, status=400)

    data_dir = os.path.join(settings.MEDIA_ROOT, dir_name, 'data')
    os.makedirs(data_dir, exist_ok=True)
    notes_path = os.path.join(data_dir, 'notes.json')

    try:
        data = _read_notes_file(notes_path)
        notes = data.get('notes', [])

        next_id = (max(n['id'] for n in notes if isinstance(n.get('id'), int)) + 1) if notes else 1
        new_note = {
            'id': next_id,
            'date': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.'),
            'note': note_text.strip()
        }
        notes.append(new_note)
        data['notes'] = notes
        _write_notes_file(notes_path, data)
        _ensure_user_edited_metadata(dir_name)
    except Exception as e:
        logger.error(f"save_note: failed to write notes for '{dir_name}': {e}")
        return JsonResponse({'error': 'Failed to save note'}, status=500)

    return JsonResponse({'status': 'ok', 'note': new_note})


@csrf_exempt
def delete_note(request):
    """
    POST /delete-note/
    Body: { "dir_name": "<str>", "note_id": <int> }
    Removes the note with the matching id from notes.json.
    Response: { "status": "ok", "deleted_id": <int> }
    """
    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, AttributeError):
        return JsonResponse({'error': 'Invalid JSON body'}, status=400)

    dir_name = str(body.get('dir_name', '')).strip()
    note_id = body.get('note_id')

    if not dir_name:
        return JsonResponse({'error': 'dir_name is required'}, status=400)
    if not isinstance(note_id, int):
        return JsonResponse({'error': 'note_id must be an integer'}, status=400)

    notes_path = os.path.join(settings.MEDIA_ROOT, dir_name, 'data', 'notes.json')

    if not os.path.exists(notes_path):
        return JsonResponse({'error': 'notes.json not found for this transcription'}, status=404)

    try:
        data = _read_notes_file(notes_path)
        original_count = len(data.get('notes', []))
        data['notes'] = [n for n in data.get('notes', []) if n.get('id') != note_id]
        if len(data['notes']) == original_count:
            logger.warning(f"delete_note: note_id={note_id} not found in '{dir_name}'")
        _write_notes_file(notes_path, data)
    except Exception as e:
        logger.error(f"delete_note: failed to update notes for '{dir_name}': {e}")
        return JsonResponse({'error': 'Failed to delete note'}, status=500)

    return JsonResponse({'status': 'ok', 'deleted_id': note_id})

