import asyncio
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
import zipfile

import save_as_mhtml as mhtml


class FilenameTests(unittest.TestCase):
    def test_safe_names(self):
        for title in ('..', '../..', '\\..\\', '  ', '\n'):
            name = mhtml.filename_for('https://example.com/', title)
            self.assertNotIn('/', name)
            self.assertNotIn('\\', name)
            self.assertNotIn(name, ('', '.', '..'))
        self.assertEqual(mhtml.filename_for('https://example.com/a/b'), 'a_b')
        self.assertLessEqual(len(mhtml.sanitize_filename('ا' * 200).encode()), 180)

    def test_invalid_urls(self):
        for url in ('file:///etc/passwd', 'https://', '-o', 'javascript:alert(1)'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                mhtml.filename_for(url)


class CaptureTests(unittest.IsolatedAsyncioTestCase):
    def fake_playwright(self, page):
        context = types.SimpleNamespace(new_page=AsyncMock(return_value=page))
        browser = types.SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())
        playwright = types.SimpleNamespace(chromium=types.SimpleNamespace(launch=AsyncMock(return_value=browser)))
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=playwright)
        manager.__aexit__ = AsyncMock(return_value=False)
        module = types.SimpleNamespace(async_playwright=lambda: manager, TimeoutError=TimeoutError)
        return browser, module

    async def test_browser_closed_on_navigation_failure(self):
        page = types.SimpleNamespace(goto=AsyncMock(side_effect=RuntimeError('failed')))
        browser, module = self.fake_playwright(page)
        with patch.dict(sys.modules, {'playwright.async_api': module}):
            with self.assertRaises(RuntimeError):
                await mhtml.save_mhtml('https://example.com', 'unused')
        browser.close.assert_awaited_once()

    async def test_http_error_is_not_archived(self):
        page = types.SimpleNamespace(goto=AsyncMock(return_value=types.SimpleNamespace(status=404)))
        browser, module = self.fake_playwright(page)
        with patch.dict(sys.modules, {'playwright.async_api': module}):
            with self.assertRaisesRegex(RuntimeError, '404'):
                await mhtml.save_mhtml('https://example.com', 'unused')
        browser.close.assert_awaited_once()


@unittest.skipUnless(os.environ.get('MELI_TEST_BROWSER'), 'browser integration test not enabled')
class BrowserIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_browser_renders_and_captures_page(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        import email
        import email.policy

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'<html><body><p id="target">before</p><script>document.querySelector("#target").textContent="rendered by browser";</script></body></html>'
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'page.mhtml'
                await mhtml.save_mhtml(f'http://127.0.0.1:{server.server_port}/', str(path),
                                       executable_path=os.environ.get('MELI_TEST_CHROMIUM'))
                message = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
                self.assertTrue(message.is_multipart())
                parts = [p for p in message.walk() if p.get_content_type() == 'text/html']
                self.assertTrue(parts)
                self.assertIn('rendered by browser', parts[0].get_content())
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


class MainTests(unittest.TestCase):
    def test_archive_and_existing_temp_untouched(self):
        async def fake_save(url, path):
            Path(path).write_text('snapshot', encoding='utf-8')
        old = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            try:
                os.chdir(tmp)
                Path('temp').mkdir()
                Path('temp/keep').write_text('keep')
                with patch.object(sys, 'argv', ['save_as_mhtml.py', '--url', 'https://example.com']), patch.object(mhtml, 'save_mhtml', fake_save):
                    mhtml.main()
                self.assertEqual(Path('temp/keep').read_text(), 'keep')
                with zipfile.ZipFile('download/example.com.zip') as z:
                    self.assertEqual(z.read('example.com.mhtml'), b'snapshot')
            finally:
                os.chdir(old)


if __name__ == '__main__':
    unittest.main()
