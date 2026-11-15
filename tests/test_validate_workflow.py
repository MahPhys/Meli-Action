import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import os
from scripts.validate_workflow import validate_folder, validate_size, validate_url


class ValidationTests(unittest.TestCase):
    def test_url(self):
        validate_url('https://example.com/a?x=1')
        for url in ('file:///etc/passwd', 'https://', 'https://x/\nfoo', '-o'):
            with self.subTest(url=url), self.assertRaises(ValueError): validate_url(url)

    def test_folders(self):
        for folder in ('', '.', '../outside', '/tmp', '.git', 'downloads/../a', '-x', 'a/.git'):
            with self.subTest(folder=folder), self.assertRaises(ValueError): validate_folder(folder)
        validate_folder('downloads/music')
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            old = os.getcwd()
            try:
                os.chdir(root)
                Path('link').symlink_to(outside)
                with self.assertRaises(ValueError): validate_folder('link/escape')
            finally: os.chdir(old)

    def test_size(self):
        validate_size('90', 95)
        validate_size('0', 95, True)
        for size in ('-1', '08', '1+1', '96', '', '0', '99999999999'):
            with self.subTest(size=size), self.assertRaises(ValueError): validate_size(size, 95)
