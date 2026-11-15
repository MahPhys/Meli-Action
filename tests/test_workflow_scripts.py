import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml


class WorkflowScripts(unittest.TestCase):
    def test_youtube_best_quality_and_quoted_arguments(self):
        workflow = yaml.safe_load(Path('.github/workflows/youtube_adv_download.yml').read_text())
        steps = workflow['jobs']['fetch-and-store']['steps']
        script = next(step['run'] for step in steps if step.get('name') == 'Download media')
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / 'yt-dlp'
            executable.write_text('#!/usr/bin/env python3\nimport sys,json,os\nopen(os.environ["ARG_LOG"],"w").write(json.dumps(sys.argv[1:]))\n')
            executable.chmod(0o755)
            values = dict(VIDEO_URL='https://example.com/video', OUTPUT_FORMAT='best (auto)',
                          VIDEO_QUALITY='best', AUDIO_QUALITY='192', VIDEO_CODEC='any (auto)',
                          CONCURRENT_FRAGMENTS='4', OUTPUT_FOLDER='downloads', TRIM_START='0:33',
                          TRIM_END='1:22', PLAYLIST_ITEMS='1,3', DOWNLOAD_SUBTITLES='true',
                          SUBTITLE_LANGS='en,fa', EMBED_METADATA='false', EMBED_CHAPTERS='false',
                          SPONSORBLOCK='false', WRITE_DESCRIPTION='false', EXTRA_ARGS='--match-title "two words"')
            env = os.environ.copy()
            env.update({'WF_GITHUB_EVENT_INPUTS_' + k: v for k, v in values.items()})
            env.update(PATH=tmp + os.pathsep + env['PATH'], RUNNER_TEMP=tmp,
                       ARG_LOG=str(Path(tmp) / 'args'), INPUT_COOKIES='', SECRET_YT_COOKIES='')
            subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], env=env, check=True)
            args = json.loads(Path(env['ARG_LOG']).read_text())
            self.assertEqual(args[args.index('--download-sections') + 1], '*0:33-1:22')
            self.assertEqual(args[args.index('--match-title') + 1], 'two words')
            self.assertIn('bestvideo+bestaudio/best', args)
            self.assertEqual(args[-1], values['VIDEO_URL'])

    def test_google_play_rejects_failed_merge_and_archives_all_splits(self):
        import shutil
        tool = shutil.which('7z')
        if not tool:
            self.skipTest('7-Zip is not available')
        workflow = yaml.safe_load(Path('.github/workflows/google_play_downloader.yml').read_text())
        steps = workflow['jobs']['download-apk']['steps']
        download = next(step['run'] for step in steps if step.get('name') == 'Download APK')
        archive = next(step['run'] for step in steps if step.get('name') == 'Create split archive (85MB chunks)')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'gplay-apk-downloader').mkdir()
            downloader = root / 'gplay-apk-downloader' / 'gplay'
            downloader.write_text('#!/bin/bash\nmkdir -p "$RUNNER_TEMP/gplay-output"\nprintf base > "$RUNNER_TEMP/gplay-output/base.apk"\nprintf split > "$RUNNER_TEMP/gplay-output/config.apk"\n')
            downloader.chmod(0o755)
            verifier = root / 'apksigner'
            verifier.write_text('#!/bin/bash\nexit 0\n')
            verifier.chmod(0o755)
            (root / 'downloads').mkdir()
            (root / 'scripts').mkdir()
            shutil.copyfile('scripts/move_outputs.py', root / 'scripts/move_outputs.py')
            env = os.environ.copy()
            env['PATH'] = tmp + os.pathsep + env['PATH']
            env.update(RUNNER_TEMP=tmp, GITHUB_WORKSPACE=tmp, WF_INPUTS_ARCHITECTURE='arm64',
                       WF_INPUTS_OUTPUT_FOLDER='downloads', WF_INPUTS_PACKAGE_NAME='com.example.app',
                       WF_INPUTS_MERGE_SPLITS='true', WF_STEPS_TIMESTAMP_OUTPUTS_VALUE='123')
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', download], cwd=root, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn('Merge did not produce exactly one APK', result.stdout)
            env['WF_INPUTS_MERGE_SPLITS'] = 'false'
            subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', download], cwd=root, env=env, check=True)
            subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', archive], cwd=root, env=env, check=True)
            archive_path = root / 'downloads' / 'com.example.app_arm64_splits_123.7z'
            listing = subprocess.check_output([tool, 'l', '-slt', str(archive_path)], text=True)
            self.assertIn('Path = base.apk', listing)
            self.assertIn('Path = config.apk', listing)

    def test_direct_download_round_trip_with_split_archive(self):
        import functools
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import shutil
        import threading
        tool = shutil.which('7z')
        if not tool:
            self.skipTest('7-Zip is not available')
        workflow = yaml.safe_load(Path('.github/workflows/url_downloader.yml').read_text())
        steps = workflow['jobs']['direct-download']['steps']
        download = next(step['run'] for step in steps if step.get('name') == 'Download File')
        archive = next(step['run'] for step in steps if step.get('name') == 'Create Split Archive')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server_dir = root / 'server'
            server_dir.mkdir()
            content = os.urandom(1024 * 1024 + 128 * 1024)
            (server_dir / 'data.bin').write_bytes(content)
            handler = functools.partial(SimpleHTTPRequestHandler, directory=str(server_dir))
            server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                output = root / 'github_output'
                env = os.environ.copy()
                env.update(WF_GITHUB_EVENT_INPUTS_FILE_URL=f'http://127.0.0.1:{server.server_port}/data.bin?token=test',
                           WF_GITHUB_EVENT_INPUTS_ZIP_PASSWORD='testpassword', WF_GITHUB_EVENT_INPUTS_MAX_PART_MB='1',
                           GITHUB_OUTPUT=str(output))
                subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', download], cwd=root, env=env, check=True)
                outputs = dict(line.split('=', 1) for line in output.read_text().splitlines())
                env['WF_STEPS_DOWNLOAD_OUTPUTS_FILEPATH'] = outputs['filepath']
                subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', archive], cwd=root, env=env, check=True)
                parts = sorted((root / 'temp_dl' / 'archive').glob('*.7z.0*'))
                self.assertGreaterEqual(len(parts), 2)
                extract = root / 'extracted'
                subprocess.run([tool, 'x', '-y', '-ptestpassword', f'-o{extract}', str(parts[0])], check=True, capture_output=True)
                self.assertEqual((extract / 'data.bin').read_bytes(), content)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_advanced_youtube_downloader_with_real_local_media(self):
        import functools
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import shutil
        import threading
        if not shutil.which('yt-dlp') or not shutil.which('ffmpeg'):
            self.skipTest('yt-dlp and ffmpeg are required for integration test')
        workflow = yaml.safe_load(Path('.github/workflows/youtube_adv_download.yml').read_text())
        script = next(s['run'] for s in workflow['jobs']['fetch-and-store']['steps'] if s.get('name') == 'Download media')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=64x64:rate=1:color=blue',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1', '-c:v', 'libx264', '-c:a', 'aac', '-pix_fmt', 'yuv420p', '-y', str(source / 'video.mp4')], check=True)
            server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(SimpleHTTPRequestHandler, directory=str(source)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                values = dict(VIDEO_URL=f'http://127.0.0.1:{server.server_port}/video.mp4', OUTPUT_FORMAT='mp4 (video)',
                              VIDEO_QUALITY='best', AUDIO_QUALITY='192', VIDEO_CODEC='any (auto)',
                              CONCURRENT_FRAGMENTS='1', OUTPUT_FOLDER='downloads', TRIM_START='', TRIM_END='',
                              PLAYLIST_ITEMS='', DOWNLOAD_SUBTITLES='false', SUBTITLE_LANGS='en', EMBED_METADATA='false',
                              EMBED_CHAPTERS='false', SPONSORBLOCK='false', WRITE_DESCRIPTION='false', EXTRA_ARGS='')
                env = os.environ.copy()
                env.update({'WF_GITHUB_EVENT_INPUTS_' + k: v for k, v in values.items()})
                env.update(RUNNER_TEMP=tmp, INPUT_COOKIES='', SECRET_YT_COOKIES='')
                subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root, env=env, check=True)
                result = list((root / 'meli-media').glob('*.mp4'))
                self.assertEqual(len(result), 1)
                self.assertEqual(result[0].read_bytes(), (source / 'video.mp4').read_bytes())
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_video_downloader_tracks_only_completed_real_ytdlp_output(self):
        import functools
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import shutil
        import threading
        if not shutil.which('yt-dlp') or not shutil.which('ffmpeg'):
            self.skipTest('yt-dlp and ffmpeg are required for integration test')
        workflow = yaml.safe_load(Path('.github/workflows/pornhub_downloader.yml').read_text())
        script = next(s['run'] for s in workflow['jobs']['download-and-maybe-split']['steps'] if s.get('name') == 'Download video (retry up to 5 times)')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'; source.mkdir()
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=size=64x64:rate=1:color=blue',
                            '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=44100', '-t', '1', '-c:v', 'libx264',
                            '-c:a', 'aac', '-pix_fmt', 'yuv420p', '-y', str(source / 'video.mp4')], check=True)
            temp_out = root / 'meli-video'; temp_out.mkdir()
            (temp_out / 'stale.part').write_bytes(b'incomplete')
            server = ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(SimpleHTTPRequestHandler, directory=str(source)))
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                env = os.environ.copy()
                env.update(RUNNER_TEMP=tmp, GITHUB_OUTPUT=str(root / 'output'), WF_GITHUB_EVENT_INPUTS_OUTPUT_FOLDER='downloads',
                           WF_GITHUB_EVENT_INPUTS_QUALITY='best', WF_GITHUB_EVENT_INPUTS_URL=f'http://127.0.0.1:{server.server_port}/video.mp4')
                subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root, env=env, check=True)
                outputs = dict(line.split('=', 1) for line in (root / 'output').read_text().splitlines())
                self.assertEqual(len(list(temp_out.iterdir())), 1)
                self.assertEqual((temp_out / outputs['filename']).read_bytes(), (source / 'video.mp4').read_bytes())
                self.assertFalse((temp_out / 'stale.part').exists())
            finally:
                server.shutdown(); server.server_close(); thread.join()

    def test_all_zip_split_steps_produce_extractable_archives(self):
        import shutil
        if not shutil.which('zip') or not shutil.which('unzip'):
            self.skipTest('zip and unzip are required')
        cases = [
            ('telegram_downloader.yml', 'download', '✂️ Split large file (if needed)', 'meli-telegram', 'telegram', 'media.bin'),
            ('youtube_adv_download.yml', 'fetch-and-store', 'Split oversized files (optional)', 'meli-media', 'advanced', 'media.bin'),
            ('youtube_downloader.yml', 'youtube-download', '✂️ Split Large File (if needed)', 'release_files', 'youtube', 'media.bin'),
            ('spotfyandsoundcloud.yml', 'media-download', 'Split Large Files', 'release_files', 'spotify', '-media.bin'),
        ]
        data = os.urandom(1024 * 1024 + 50 * 1024)
        for filename, job, step, folder, variant, basename in cases:
            with self.subTest(workflow=filename), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = root / folder; target.mkdir()
                (target / basename).write_bytes(data)
                workflow = yaml.safe_load((Path('.github/workflows') / filename).read_text())
                script = next(s['run'] for s in workflow['jobs'][job]['steps'] if s.get('name') == step)
                env = os.environ.copy()
                env.update(RUNNER_TEMP=tmp, WF_GITHUB_EVENT_INPUTS_SPLIT_THRESHOLD_MB='1',
                           WF_STEPS_DOWNLOAD_OUTPUTS_DOWNLOADED_NAME=basename, WF_STEPS_DOWNLOAD_OUTPUTS_FILE_SIZE=str(len(data)),
                           WF_GITHUB_EVENT_INPUTS_OUTPUT_FOLDER='downloads', WF_GITHUB_EVENT_INPUTS_MAX_PART_MB='1',
                           WF_STEPS_RETRIEVE_OUTPUTS_FILENAME=basename)
                subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root, env=env, check=True, capture_output=True)
                archives = list(target.glob('*.zip'))
                self.assertEqual(len(archives), 1)
                self.assertFalse((target / basename).exists())
                joined = root / 'joined.zip'
                subprocess.run(['zip', '-s', '0', str(archives[0]), '--out', str(joined)], check=True, capture_output=True)
                output = subprocess.check_output(['unzip', '-p', str(joined)])
                self.assertEqual(output, data)

    def test_google_play_refuses_invalid_signature(self):
        workflow = yaml.safe_load(Path('.github/workflows/google_play_downloader.yml').read_text())
        script = next(s['run'] for s in workflow['jobs']['download-apk']['steps'] if s.get('name') == 'Download APK')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'gplay-apk-downloader').mkdir()
            fake = root / 'gplay-apk-downloader' / 'gplay'
            fake.write_text('#!/bin/bash\nmkdir -p "$RUNNER_TEMP/gplay-output"\nprintf invalid > "$RUNNER_TEMP/gplay-output/merged.apk"\n')
            fake.chmod(0o755)
            signer = root / 'apksigner'; signer.write_text('#!/bin/bash\nexit 1\n'); signer.chmod(0o755)
            env = os.environ.copy()
            env.update(PATH=tmp + os.pathsep + env['PATH'], RUNNER_TEMP=tmp, WF_INPUTS_ARCHITECTURE='arm64',
                       WF_INPUTS_OUTPUT_FOLDER='downloads', WF_INPUTS_PACKAGE_NAME='com.example.app', WF_INPUTS_MERGE_SPLITS='true')
            result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('signature verification failed', result.stdout)

    def test_youtube_cookie_file_is_private_and_deleted(self):
        workflow = yaml.safe_load(Path('.github/workflows/youtube_adv_download.yml').read_text())
        script = next(s['run'] for s in workflow['jobs']['fetch-and-store']['steps'] if s.get('name') == 'Download media')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fake = root / 'yt-dlp'
            fake.write_text('''#!/usr/bin/env python3
import json, os, stat, sys
args = sys.argv[1:]
p = args[args.index('--cookies') + 1]
open(os.environ['ARG_LOG'], 'w').write(json.dumps({'path':p, 'mode':stat.S_IMODE(os.stat(p).st_mode)}))
''')
            fake.chmod(0o755)
            values = dict(VIDEO_URL='https://example.com/video', OUTPUT_FORMAT='best (auto)', VIDEO_QUALITY='best',
                          AUDIO_QUALITY='192', VIDEO_CODEC='vp9', CONCURRENT_FRAGMENTS='1', OUTPUT_FOLDER='downloads',
                          TRIM_START='', TRIM_END='', PLAYLIST_ITEMS='', DOWNLOAD_SUBTITLES='false', SUBTITLE_LANGS='en',
                          EMBED_METADATA='false', EMBED_CHAPTERS='false', SPONSORBLOCK='false', WRITE_DESCRIPTION='false', EXTRA_ARGS='')
            env = os.environ.copy(); env.update({'WF_GITHUB_EVENT_INPUTS_' + k: v for k,v in values.items()})
            env.update(PATH=tmp+os.pathsep+env['PATH'], RUNNER_TEMP=tmp, ARG_LOG=str(root/'args.json'),
                       INPUT_COOKIES='', SECRET_YT_COOKIES='private-cookie')
            subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], env=env, check=True)
            data = json.loads((root/'args.json').read_text())
            self.assertEqual(data['mode'], 0o600)
            self.assertFalse(Path(data['path']).exists())

    def test_release_steps_remain_separate_from_push_steps(self):
        for filename, job in [('url_downloader.yml', 'direct-download'),
                              ('youtube_downloader.yml', 'youtube-download'),
                              ('spotfyandsoundcloud.yml', 'media-download')]:
            with self.subTest(workflow=filename):
                workflow = yaml.safe_load((Path('.github/workflows') / filename).read_text())
                steps = workflow['jobs'][job]['steps']
                release = [s for s in steps if str(s.get('uses', '')).startswith('softprops/action-gh-release@')]
                self.assertEqual(len(release), 1)
                self.assertTrue(release[0]['with']['files'])

    def test_simple_youtube_rejects_untrusted_service_urls(self):
        import shutil
        workflow = yaml.safe_load(Path('.github/workflows/youtube_downloader.yml').read_text())
        script = next(s['run'] for s in workflow['jobs']['youtube-download']['steps'] if s.get('id') == 'retrieve')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'scripts').mkdir()
            shutil.copyfile('scripts/validate_workflow.py', root / 'scripts/validate_workflow.py')
            (root / 'sitecustomize.py').write_text('import time\ntime.sleep=lambda x: None\n')
            (root / 'requests.py').write_text('''import os
class Response:
    def __init__(self, data): self.data=data
    def raise_for_status(self): pass
    def json(self): return self.data
class Session:
    def __init__(self): self.headers={}
    def get(self, url, timeout=None):
        if url == 'https://media.ytmp3.gg/': return Response({})
        return Response({'status':'completed', 'downloadUrl':os.environ['DL_URL']})
    def post(self, url, json, timeout=None):
        return Response({'statusUrl':os.environ['STATUS_URL'], 'title':'safe\\nmalicious=ignored'})
''')
            env = os.environ.copy()
            env.update(PYTHONPATH=tmp, INPUT_URL='https://youtu.be/abcdefghijk', INPUT_FORMAT='mp4',
                       INPUT_QUALITY='720p', GITHUB_OUTPUT=str(root / 'output'),
                       STATUS_URL='https://status.example/path', DL_URL='https://download.example/file')
            for var, value, message in [('STATUS_URL', 'file:///etc/passwd', 'invalid status URL'),
                                        ('DL_URL', '--output', 'invalid download URL')]:
                with self.subTest(var=var):
                    bad = env.copy(); bad[var] = value
                    result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root, env=bad, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stdout + result.stderr)
                    self.assertFalse((root / '.download_info').exists())
            subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root, env=env, check=True)
            lines = (root / 'output').read_text().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('title=safe malicious=ignored', lines)

    def test_split_refuses_to_overwrite_existing_parts(self):
        cases = [('spotify', 'spotfyandsoundcloud.yml', 'media-download', 'Split Large Files', 'release_files'),
                 ('advanced', 'youtube_adv_download.yml', 'fetch-and-store', 'Split oversized files (optional)', 'meli-media')]
        for name, filename, job, step, folder in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp); target = root / folder; target.mkdir()
                original = target / 'track.mp3'; original.write_bytes(os.urandom(1024*1024 + 1))
                existing = target / 'track.mp3.z01'; existing.write_bytes(b'keep me')
                workflow = yaml.safe_load((Path('.github/workflows') / filename).read_text())
                script = next(s['run'] for s in workflow['jobs'][job]['steps'] if s.get('name') == step)
                env = os.environ.copy(); env.update(RUNNER_TEMP=tmp, WF_GITHUB_EVENT_INPUTS_OUTPUT_FOLDER='downloads', WF_GITHUB_EVENT_INPUTS_MAX_PART_MB='1')
                result = subprocess.run(['bash', '-e', '-o', 'pipefail', '-c', script], cwd=root, env=env, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(existing.read_bytes(), b'keep me')
                self.assertTrue(original.exists())
