from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import errno
from scripts.move_outputs import move_outputs


class MoveOutputsTests(unittest.TestCase):
    def test_moves_all_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / 'source', Path(tmp) / 'dest'
            source.mkdir()
            (source / 'one').write_bytes(b'one')
            (source / 'two').write_bytes(b'two')
            self.assertEqual(len(move_outputs(source, dest)), 2)
            self.assertEqual((dest / 'one').read_bytes(), b'one')
            self.assertFalse((source / 'one').exists())

    def test_existing_file_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / 'source', Path(tmp) / 'dest'
            source.mkdir(); dest.mkdir()
            (source / 'one').write_bytes(b'new')
            (dest / 'one').write_bytes(b'old')
            with self.assertRaises(FileExistsError): move_outputs(source, dest)
            self.assertEqual((dest / 'one').read_bytes(), b'old')
            self.assertEqual((source / 'one').read_bytes(), b'new')

    def test_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / 'source', Path(tmp) / 'dest'
            source.mkdir()
            (source / 'link').symlink_to('/etc/passwd')
            with self.assertRaises(ValueError): move_outputs(source, dest)
            self.assertFalse(dest.exists())

    def test_rolls_back_after_copy_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, dest = Path(tmp) / 'source', Path(tmp) / 'dest'
            source.mkdir(); dest.mkdir()
            (source / 'one').write_bytes(b'one')
            (source / 'two').write_bytes(b'two')
            with patch('scripts.move_outputs.os.link', side_effect=OSError(errno.EXDEV, 'different device')):
                with patch('scripts.move_outputs.shutil.copyfileobj', side_effect=OSError('disk full')):
                    with self.assertRaises(OSError): move_outputs(source, dest)
            self.assertEqual(list(dest.iterdir()), [])
            self.assertEqual(len(list(source.iterdir())), 2)
