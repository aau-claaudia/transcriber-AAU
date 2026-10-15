import os
import secrets
import stat
import fcntl
from pathlib import Path


def private_directory(path):
    path = Path(path).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("Private storage must not use symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError("Private storage must be a directory owned by the running user")
    path.chmod(0o700)
    return path


def initialize_storage(root):
    os.umask(0o077)
    root = private_directory(root)
    for name in ("media", "jobs", "logs", "secrets", "tmp"):
        private_directory(root / name)
    secret_path = root / "secrets" / "django.key"
    flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
    with os.fdopen(os.open(secret_path, flags, 0o600), "r+") as secret_file:
        info = os.fstat(secret_file.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1:
            raise ValueError("Secret must be a private file owned by the running user")
        fcntl.flock(secret_file.fileno(), fcntl.LOCK_EX)
        os.fchmod(secret_file.fileno(), 0o600)
        secret = secret_file.read().strip()
        if not secret:
            secret = secrets.token_urlsafe(64)
            secret_file.write(secret)
            secret_file.flush()
            os.fsync(secret_file.fileno())
    return root, secret