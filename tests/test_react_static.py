"""빌드 파일 제공·JS MIME·포트 중복 실행을 실제 로컬 HTTP로 검사한다."""
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from backend.server import create_server


class ReactStaticTests(unittest.TestCase):
    def test_build_assets_and_source_separation_and_exclusive_port(self):
        with tempfile.TemporaryDirectory() as temporary, patch('backend.server.ROOT', Path(temporary)):
            root = Path(temporary)
            dist = root / 'frontend/dist'
            (dist / 'assets').mkdir(parents=True)
            (dist / 'index.html').write_text('<script type="module" src="/assets/app.js"></script>', encoding='utf-8')
            (dist / 'assets/app.js').write_text('export const ready = true;', encoding='utf-8')
            (root / 'frontend/src').mkdir()
            (root / 'frontend/src/main.jsx').write_text('source must not be served', encoding='utf-8')
            server = create_server(0)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                with urlopen(base, timeout=5) as response:
                    self.assertIn('/assets/app.js', response.read().decode())
                with urlopen(base + '/assets/app.js', timeout=5) as response:
                    self.assertEqual(response.headers.get_content_type(), 'text/javascript')
                    self.assertIn(b'export const ready', response.read())
                with self.assertRaises(HTTPError) as missing:
                    urlopen(base + '/src/main.jsx', timeout=5)
                self.assertEqual(missing.exception.code, 404)
                with self.assertRaises(OSError):
                    duplicate = create_server(server.server_port)
                    duplicate.server_close()
                (dist / 'index.html').unlink()
                with self.assertRaises(HTTPError) as unbuilt:
                    urlopen(base, timeout=5)
                self.assertEqual(unbuilt.exception.code, 503)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
