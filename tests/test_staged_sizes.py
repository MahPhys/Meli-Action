import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts.check_staged_sizes import find_oversized


class StagedSizeTests(unittest.TestCase):
    def test_reads_index_and_handles_unusual_filenames(self):
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                subprocess.run(['git', 'init', '-q'], check=True)
                Path('normal').write_bytes(b'12345')
                Path('new\nline\tname').write_bytes(b'abcdef')
                subprocess.run(['git', 'add', '--', '.'], check=True)
                # Working-tree size differs from staged content.
                Path('normal').write_bytes(b'changed without staging')
                oversized = find_oversized(limit=5)
                self.assertEqual(oversized, [('new\nline\tname', 6)])
            finally:
                os.chdir(old)

    def test_empty_index(self):
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                subprocess.run(['git', 'init', '-q'], check=True)
                self.assertEqual(find_oversized(), [])
            finally:
                os.chdir(old)
