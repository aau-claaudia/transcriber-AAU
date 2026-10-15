import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from .hpc_files import list_directory, validate_selection


class HpcFileTests(SimpleTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.storage = self.root / 'private'
        self.storage.mkdir()
        self.source = self.root / 'speech.wav'
        self.source.write_bytes(b'audio')
        overrides = override_settings(INPUT_ROOTS={'home': str(self.root)}, DATA_ROOT=self.storage)
        overrides.enable()
        self.addCleanup(overrides.disable)

    def test_listing_and_signed_selection(self):
        (self.root / 'folder').mkdir()
        listing = list_directory('home')
        self.assertEqual({entry['name'] for entry in listing['entries']}, {'folder', 'speech.wav'})
        entry = next(entry for entry in listing['entries'] if entry['kind'] == 'file')
        self.assertEqual(validate_selection(entry['token'])['path'], 'speech.wav')

    def test_rejects_traversal_hidden_and_unknown_root(self):
        for root, path in [('home', '../'), ('home', '/etc'), ('other', ''), ('home', '.ssh')]:
            with self.subTest(root=root, path=path), self.assertRaises(ValueError):
                list_directory(root, path)

    def test_symlinks_and_private_storage_are_not_listed(self):
        (self.root / 'link.wav').symlink_to(self.source)
        (self.root / 'folder').symlink_to(self.storage, target_is_directory=True)
        self.assertEqual([entry['name'] for entry in list_directory('home')['entries']], ['speech.wav'])
        with self.assertRaises(OSError):
            list_directory('home', 'folder')
        with self.assertRaises(ValueError):
            list_directory('home', 'private')

    def test_changed_source_and_forged_token_rejected(self):
        token = list_directory('home')['entries'][0]['token']
        self.source.write_bytes(b'changed audio')
        with self.assertRaises(ValueError):
            validate_selection(token)
        with self.assertRaises(ValueError):
            validate_selection(token + 'forged')

    def test_replacement_symlink_rejected(self):
        token = list_directory('home')['entries'][0]['token']
        self.source.unlink()
        self.source.symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            validate_selection(token)

    def test_listing_pagination(self):
        for index in range(110):
            (self.root / f'{index:03}.wav').write_bytes(b'audio')
        self.assertEqual(list_directory('home')['next_offset'], 100)
        self.assertIsNone(list_directory('home', offset=100)['next_offset'])