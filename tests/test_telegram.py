import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import requests
import telegram_downloader as telegram


def prepare_partial(path, content, url='https://example.com'):
    partial = Path(str(path) + '.partial')
    partial.write_bytes(content)
    telegram._save_validator(partial, url, '"version-one"')
    return partial


def response(status, data, headers):
    result = Mock(status_code=status, headers=headers)
    result.iter_content.return_value = [data]
    return result


class TelegramTests(unittest.TestCase):
    def test_range_ignored_restarts_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            prepare_partial(path, b'partial')
            session = Mock(headers={})
            session.get.return_value = response(200, b'complete', {'content-length': '8'})
            with patch.object(requests, 'Session', return_value=session):
                self.assertTrue(telegram.download_with_resume('https://example.com', path, {}))
            self.assertEqual(path.read_bytes(), b'complete')

    def test_valid_range_is_appended(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            prepare_partial(path, b'abc')
            session = Mock(headers={})
            session.get.return_value = response(206, b'def', {'content-length': '3', 'Content-Range': 'bytes 3-5/6', 'ETag': '"version-one"'})
            with patch.object(requests, 'Session', return_value=session):
                self.assertTrue(telegram.download_with_resume('https://example.com', path, {}))
            self.assertEqual(path.read_bytes(), b'abcdef')

    def test_invalid_range_does_not_publish(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            prepare_partial(path, b'abc')
            session = Mock(headers={})
            session.get.return_value = response(206, b'def', {'content-length': '3', 'Content-Range': 'bytes 0-2/6', 'ETag': '"version-one"'})
            with patch.object(requests, 'Session', return_value=session):
                self.assertFalse(telegram.download_with_resume('https://example.com', path, {}))
            self.assertFalse(path.exists())

class TelegramHTTPIntegrationTests(unittest.TestCase):
    def test_resume_against_local_http_server(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(206)
                self.send_header('Content-Range', 'bytes 3-5/6')
                self.send_header('Content-Length', '3')
                self.send_header('ETag', '"version-one"')
                self.end_headers()
                self.wfile.write(b'def')
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as d:
                path = Path(d) / 'file'
                url = f'http://127.0.0.1:{server.server_port}/file'
                prepare_partial(path, b'abc', url)
                self.assertTrue(telegram.download_with_resume(url, path, {}))
                self.assertEqual(path.read_bytes(), b'abcdef')
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

class TelegramRangeTests(unittest.TestCase):
    def test_range_shorter_than_resource_is_not_published(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            prepare_partial(path, b'abc')
            session = Mock(headers={})
            session.get.return_value = response(206, b'def', {'content-length': '3', 'Content-Range': 'bytes 3-5/9', 'ETag': '"version-one"'})
            with patch.object(requests, 'Session', return_value=session), patch.object(telegram.time, 'sleep'):
                self.assertFalse(telegram.download_with_resume('https://example.com', path, {}, max_retries=1))
            self.assertFalse(path.exists())
            self.assertEqual(Path(str(path) + '.partial').read_bytes(), b'abcdef')

    def test_malformed_range_does_not_append(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            partial = Path(str(path) + '.partial')
            prepare_partial(path, b'abc')
            session = Mock(headers={})
            session.get.return_value = response(206, b'def', {'content-length': '3', 'Content-Range': 'bytes 3-5/5', 'ETag': '"version-one"'})
            with patch.object(requests, 'Session', return_value=session):
                self.assertFalse(telegram.download_with_resume('https://example.com', path, {}))
            self.assertEqual(partial.read_bytes(), b'abc')

class TelegramValidatorTests(unittest.TestCase):
    def test_existing_partial_without_metadata_restarts(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            Path(str(path) + '.partial').write_bytes(b'old')
            session = Mock(headers={})
            session.get.return_value = response(200, b'new-data', {'content-length': '8'})
            with patch.object(requests, 'Session', return_value=session):
                self.assertTrue(telegram.download_with_resume('https://example.com', path, {}))
            self.assertEqual(path.read_bytes(), b'new-data')
            self.assertEqual(session.get.call_args.kwargs['headers'], {})

    def test_changed_validator_never_appends_old_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            prepare_partial(path, b'old')
            session = Mock(headers={})
            session.get.side_effect = [
                response(206, b'xyz', {'content-length': '3', 'Content-Range': 'bytes 3-5/6', 'ETag': '"different"'}),
                response(200, b'new-data', {'content-length': '8', 'ETag': '"different"'}),
            ]
            with patch.object(requests, 'Session', return_value=session), patch.object(telegram.time, 'sleep'):
                self.assertTrue(telegram.download_with_resume('https://example.com', path, {}, max_retries=2))
            self.assertEqual(path.read_bytes(), b'new-data')
            self.assertEqual(session.get.call_args_list[0].kwargs['headers']['If-Range'], '"version-one"')
            self.assertEqual(session.get.call_args_list[1].kwargs['headers'], {})

    def test_changed_url_does_not_reuse_partial(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'file'
            prepare_partial(path, b'old', 'https://example.com/one')
            session = Mock(headers={})
            session.get.return_value = response(200, b'other', {'content-length': '5'})
            with patch.object(requests, 'Session', return_value=session):
                self.assertTrue(telegram.download_with_resume('https://example.com/two', path, {}))
            self.assertEqual(path.read_bytes(), b'other')
            self.assertEqual(session.get.call_args.kwargs['headers'], {})
