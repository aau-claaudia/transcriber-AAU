import os
import stat
from contextlib import contextmanager
from pathlib import Path

from django.conf import settings
from django.core import signing


def root_options():
    return [{'id': name, 'label': name} for name in settings.INPUT_ROOTS]


def _parts(relative):
    if not isinstance(relative, str) or relative.startswith('/') or '\\' in relative:
        raise ValueError('Invalid relative path')
    parts = relative.split('/') if relative else []
    if any(not part or part.startswith('.') for part in parts):
        raise ValueError('Hidden files and path traversal are not permitted')
    return parts


@contextmanager
def open_entry(root_id, relative, directory=False):
    if root_id not in settings.INPUT_ROOTS:
        raise ValueError('Unknown storage root')
    parts = _parts(relative)
    root = Path(settings.INPUT_ROOTS[root_id]).resolve(strict=True)
    target = root.joinpath(*parts)
    private_root = Path(settings.DATA_ROOT).resolve()
    if target == private_root or private_root in target.parents:
        raise ValueError('Application storage cannot be selected')
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for index, part in enumerate(parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if directory or index < len(parts) - 1:
                flags |= os.O_DIRECTORY
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        info = os.fstat(descriptor)
        if directory and not stat.S_ISDIR(info.st_mode):
            raise ValueError('Not a directory')
        if not directory and not stat.S_ISREG(info.st_mode):
            raise ValueError('Only regular files can be selected')
        yield descriptor
    finally:
        os.close(descriptor)


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def list_directory(root_id, relative='', offset=0):
    if offset < 0:
        raise ValueError('Invalid listing offset')
    with open_entry(root_id, relative, directory=True) as descriptor:
        names = sorted(name for name in os.listdir(descriptor) if not name.startswith('.'))
        entries = []
        for name in names[offset:offset + 100]:
            path = f'{relative}/{name}' if relative else name
            try:
                info = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
                if stat.S_ISDIR(info.st_mode):
                    with open_entry(root_id, path, directory=True):
                        pass
                    entries.append({'name': name, 'path': path, 'kind': 'directory'})
                elif stat.S_ISREG(info.st_mode) and Path(name).suffix.lower() in settings.ALLOWED_AUDIO_EXTENSIONS:
                    with open_entry(root_id, path) as file_descriptor:
                        info = os.fstat(file_descriptor)
                    token = signing.dumps({'root': root_id, 'path': path,
                                           'fingerprint': fingerprint(info)}, salt='hpc-input')
                    entries.append({'name': name, 'path': path, 'kind': 'file',
                                    'size': info.st_size, 'token': token, 'root': root_id})
            except (OSError, ValueError):
                continue
        next_offset = offset + 100 if offset + 100 < len(names) else None
    return {'root': root_id, 'path': relative, 'entries': entries, 'next_offset': next_offset}


def validate_selection(token):
    try:
        selection = signing.loads(token, salt='hpc-input', max_age=3600)
        with open_entry(selection['root'], selection['path']) as descriptor:
            info = os.fstat(descriptor)
            if fingerprint(info) != selection['fingerprint']:
                raise ValueError('Selected file changed; refresh the file browser')
        if Path(selection['path']).suffix.lower() not in settings.ALLOWED_AUDIO_EXTENSIONS:
            raise ValueError('Unsupported file extension')
        return selection
    except (signing.BadSignature, KeyError, TypeError, OSError) as error:
        raise ValueError('File selection expired or is no longer accessible') from error