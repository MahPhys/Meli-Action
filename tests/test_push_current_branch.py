import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'push_current_branch.sh'


class PushTests(unittest.TestCase):
    def run_script(self, overrides=None):
        with tempfile.TemporaryDirectory() as tmp:
            git = Path(tmp) / 'git'
            git.write_text('''#!/usr/bin/env python3
import json, os, sys
args=sys.argv[1:]
if args[0]=='check-ref-format': sys.exit(0)
if args[:2]==['remote','get-url']:
    print(os.environ['MOCK_PUSH'] if '--push' in args else os.environ['MOCK_FETCH'])
elif args[0]=='push':
    open(os.environ['MOCK_LOG'],'w').write(json.dumps({'args':args, 'header':os.environ['GIT_CONFIG_VALUE_0'], 'key':os.environ['GIT_CONFIG_KEY_0']}))
''')
            git.chmod(0o755)
            log = Path(tmp) / 'log'
            env = os.environ.copy()
            env.update(PATH=tmp + os.pathsep + env['PATH'], GITHUB_TOKEN='test-token',
                       GITHUB_REF='refs/heads/feature/test', GITHUB_REF_TYPE='branch',
                       GITHUB_SERVER_URL='https://github.com', GITHUB_REPOSITORY='owner/repo',
                       MOCK_FETCH='https://github.com/owner/repo', MOCK_PUSH='https://github.com/owner/repo', MOCK_LOG=str(log))
            env.update(overrides or {})
            result = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
            return result, json.loads(log.read_text()) if log.exists() else None

    def test_pushes_only_to_triggering_branch_with_step_scoped_header(self):
        result, log = self.run_script()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(log['args'], ['push', 'origin', 'HEAD:refs/heads/feature/test'])
        self.assertEqual(log['key'], 'http.https://github.com/.extraheader')
        self.assertEqual(base64.b64decode(log['header'].split()[-1]), b'x-access-token:test-token')
        self.assertNotIn('test-token', result.stdout + result.stderr)

    def test_rejects_tag_or_wrong_origin(self):
        for overrides in ({'GITHUB_REF_TYPE':'tag', 'GITHUB_REF':'refs/tags/release'},
                          {'MOCK_FETCH':'https://github.com/evil/repo'}, {'MOCK_PUSH':'https://example.com/other'},
                          {'MOCK_PUSH':'https://github.com/owner/repo\nhttps://example.com/other'},
                          {'GITHUB_REF':'refs/tags/disguised'}):
            with self.subTest(overrides=overrides):
                result, log = self.run_script(overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIsNone(log)

    def test_push_to_local_smart_http_git_server(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Thread
        import urllib.parse
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bare = root / 'owner' / 'repo.git'; bare.parent.mkdir()
            subprocess.run(['git', 'init', '--bare', '-q', str(bare)], check=True)
            subprocess.run(['git', '--git-dir', str(bare), 'config', 'http.receivepack', 'true'], check=True)
            work = root / 'work'; work.mkdir()
            subprocess.run(['git', 'init', '-q', '-b', 'feature'], cwd=work, check=True)
            subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=work, check=True)
            subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=work, check=True)
            (work / 'data').write_text('hello')
            subprocess.run(['git', 'add', 'data'], cwd=work, check=True)
            subprocess.run(['git', 'commit', '-q', '-m', 'test'], cwd=work, check=True)
            authorization = []
            class Handler(BaseHTTPRequestHandler):
                def do_GET(self): self.run_backend()
                def do_POST(self): self.run_backend()
                def log_message(self, *args): pass
                def run_backend(self):
                    authorization.append(self.headers.get('Authorization'))
                    parsed = urllib.parse.urlsplit(self.path)
                    length = int(self.headers.get('Content-Length', '0'))
                    body = self.rfile.read(length)
                    env = os.environ.copy()
                    env.update(GIT_PROJECT_ROOT=tmp, GIT_HTTP_EXPORT_ALL='1', PATH_INFO=parsed.path,
                               QUERY_STRING=parsed.query, REQUEST_METHOD=self.command,
                               CONTENT_TYPE=self.headers.get('Content-Type', ''), CONTENT_LENGTH=str(length), REMOTE_USER='test')
                    proc = subprocess.run(['git', 'http-backend'], env=env, input=body, capture_output=True, check=True)
                    headers, payload = proc.stdout.split(b'\r\n\r\n', 1)
                    lines = headers.decode('latin1').split('\r\n')
                    status = next((int(x.split(':', 1)[1].strip().split()[0]) for x in lines if x.lower().startswith('status:')), 200)
                    self.send_response(status)
                    for line in lines:
                        key, value = line.split(':', 1)
                        if key.lower() not in ('status', 'transfer-encoding'):
                            self.send_header(key, value.strip())
                    self.end_headers(); self.wfile.write(payload)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                origin = f'http://127.0.0.1:{server.server_port}'
                subprocess.run(['git', 'remote', 'add', 'origin', origin + '/owner/repo.git'], cwd=work, check=True)
                env = os.environ.copy()
                env.update(GITHUB_TOKEN='test-token', GITHUB_REF='refs/heads/feature', GITHUB_REF_TYPE='branch',
                           GITHUB_SERVER_URL=origin, GITHUB_REPOSITORY='owner/repo', NO_PROXY='127.0.0.1,localhost')
                subprocess.run(['bash', str(SCRIPT)], cwd=work, env=env, check=True, capture_output=True)
                local = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=work)
                remote = subprocess.check_output(['git', '--git-dir', str(bare), 'rev-parse', 'refs/heads/feature'])
                self.assertEqual(local, remote)
                self.assertTrue(authorization)
                self.assertTrue(all(x == 'basic ' + base64.b64encode(b'x-access-token:test-token').decode() for x in authorization))
            finally:
                server.shutdown(); server.server_close(); thread.join()
