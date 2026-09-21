"""POC 静态服务 + 结果回传:GET 出静态页,POST /result 收录制的视频。"""
import json
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).parent / "browserpoc-dist"
RESULT = {"done": False, "file": None, "meta": None, "reports": []}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(ROOT), **kw)

    def log_message(self, *a):  # 静音
        pass

    def do_GET(self):
        if self.path == "/status":
            body = json.dumps(RESULT).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/report":
            length = int(self.headers.get("content-length") or 0)
            data = json.loads(self.rfile.read(length) or b"{}")
            RESULT["reports"].append(data)
            print("report:", data, flush=True)
            self.send_response(200)
            self.send_header("content-length", "2")
            self.end_headers()
            self.wfile.write(b"{}")
            return
        if self.path != "/result":
            self.send_error(404)
            return
        name = self.headers.get("x-filename", "poc.webm")
        meta = {"secs": self.headers.get("x-secs"), "mime": self.headers.get("x-mime"),
                "size": self.headers.get("content-length")}
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        out = ROOT / f"result_{int(time.time())}.{name.rsplit('.', 1)[-1]}"
        out.write_bytes(body)
        RESULT.update(done=True, file=str(out), meta=meta)
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"{}")


if __name__ == "__main__":
    print("POC server on http://127.0.0.1:8633", flush=True)
    HTTPServer(("127.0.0.1", 8633), Handler).serve_forever()
