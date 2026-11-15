"""Serve ONLY the executor and the plan files to the logged-in Odoo tab, on 127.0.0.1 (this machine only).
Usage: python -I lib/serve_pack.py <work_dir> [port]   (stop it when the run is done)"""
import os, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

W = Path(sys.argv[1]).resolve(); PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
ALLOWED_ORIGINS = {o for o in os.environ.get('PC_ORIGINS', '').split(',') if o}  # e.g. https://<db>.odoo.com,https://<staging-db>.dev.odoo.com
ALLOWED = {'executor_prod.js'} | {f'prod_pack/{p.name}' for p in (W / 'prod_pack').glob('*.txt')} | \
          {f'data/{n}' for n in ('r5_c_variants.txt', 'r5_c_merge.txt', 'r6_c_movespec.txt', 'r5_c_renames.txt')}


class H(BaseHTTPRequestHandler):
    def _cors(self):
        o = self.headers.get('Origin', '')
        if o in ALLOWED_ORIGINS:
            self.send_header('Access-Control-Allow-Origin', o)
            self.send_header('Access-Control-Allow-Private-Network', 'true')
            self.send_header('Access-Control-Allow-Methods', 'GET')
            self.send_header('Access-Control-Allow-Headers', '*')
        self.send_header('Cache-Control', 'no-store')

    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()

    def do_GET(self):
        rel = self.path.lstrip('/').split('?')[0]
        if rel not in ALLOWED or not (W / rel).is_file():
            self.send_response(404); self._cors(); self.end_headers(); return
        b = (W / rel).read_bytes()
        self.send_response(200); self._cors(); self.send_header('Content-Type', 'text/plain; charset=utf-8'); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)

    def log_message(self, *a):
        pass


ThreadingHTTPServer(('127.0.0.1', PORT), H).serve_forever()
