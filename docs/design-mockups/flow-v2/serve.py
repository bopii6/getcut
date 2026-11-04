from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import os
os.chdir(Path(__file__).parent)
class Handler(SimpleHTTPRequestHandler):
 def do_POST(self):
  name=self.path.removeprefix('/capture/')
  if self.path.startswith('/capture/') and name in [f'{i:02d}.png' for i in range(1,7)]:
   data=self.rfile.read(int(self.headers.get('Content-Length','0')))
   Path(name).write_bytes(data)
   self.send_response(200);self.end_headers();self.wfile.write(b'saved')
  else:
   self.send_error(404)
HTTPServer(('127.0.0.1',8769),Handler).serve_forever()
