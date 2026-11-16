"""Receive JSON extracts POSTed from the logged-in Odoo tab, on 127.0.0.1 only. Writes data/dd/<name>.json.
Usage: python -I lib/recv_json.py <work_dir> [port]   (stop it when the extract is saved)"""
import json, os, re, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

W = Path(sys.argv[1]).resolve(); PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8766
OUT = W / 'data' / 'dd'; OUT.mkdir(parents=True, exist_ok=True)
ORIGINS = {o for o in os.environ.get('PC_ORIGINS', '').split(',') if o}  # e.g. https://<db>.odoo.com


class H(BaseHTTPRequestHandler):
    def _cors(self):
        o = self.headers.get('Origin', '')
        if o in ORIGINS:
            self.send_header('Access-Control-Allow-Origin', o)
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Access-Control-Allow-Methods', 'POST')
            self.send_header('Access-Control-Allow-Headers', '*')

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_POST(self):
        if self.headers.get('Origin', '') not in ORIGINS:
            self.send_response(403); self.end_headers(); return
        name = parse_qs(urlparse(self.path).query).get('name', ['x'])[0]
        if not re.fullmatch(r'[a-z0-9_]{1,40}', name):
            self.send_response(400); self.end_headers(); return
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        json.loads(body)  # must be valid JSON
        (OUT / f'{name}.json').write_bytes(body)
        self.send_response(200); self._cors(); self.end_headers(); self.wfile.write(b'ok')
        print('saved', name, len(body), flush=True)


ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
