import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from transcriber.private_storage import initialize_storage, private_directory


class PrivateStorageTests(unittest.TestCase):
    def setUp(self):
        self.old_umask = os.umask(0o077)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.addCleanup(os.umask, self.old_umask)
        self.root = Path(self.temporary.name)

    def test_private_layout_and_stable_secret(self):
        root, secret = initialize_storage(self.root / "user-a")
        self.assertEqual(initialize_storage(root)[1], secret)
        for name in ("", "media", "jobs", "logs", "secrets", "tmp"):
            self.assertEqual(stat.S_IMODE((root / name).stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((root / "secrets/django.key").stat().st_mode), 0o600)
        self.assertNotEqual(initialize_storage(self.root / "user-b")[1], secret)

    def test_rejects_symlink_directory(self):
        (self.root / "link").symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            private_directory(self.root / "link" / "child")

    def test_rejects_foreign_owner(self):
        with patch("transcriber.private_storage.os.getuid", return_value=os.getuid() + 1):
            with self.assertRaises(ValueError):
                private_directory(self.root)

    def test_rejects_symlink_secret(self):
        root, _ = initialize_storage(self.root / "user")
        secret_path = root / "secrets/django.key"
        secret_path.unlink()
        secret_path.symlink_to(self.root / "other-secret")
        with self.assertRaises(OSError):
            initialize_storage(root)