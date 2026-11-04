"""首页方案A本地验收桩：静态服 poc/ + 假 /api。
复刻 pages.py 的 / 服务方式（poc/index.html + <base href="/poc/">）。
GET /api/me?mode=out 返回 404 即未登录态；默认登录态。
"""
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

POC = Path(r"E:\短视频生成\videogen_hotfix\videogen\server_static\poc")
LOGGED_OUT = "--out" in sys.argv

ME = {"email": "creator2997@example.com", "tier": "premium", "tier_label": "高级版",
      "is_admin": False, "nickname": "创作者2997", "avatar": "🦊",
      "created": "2026-09-01", "avatars": ["🦊"], "builds_today": 0, "free_daily_builds": 2}


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if isinstance(body, bytes):
            self.wfile.write(body)
        else:
            self.wfile.write(body.encode("utf-8"))

    def do_GET(self):
        p = self.path.split("?")[0]
        if p.startswith("/api/"):
            if p == "/api/me" and not LOGGED_OUT:
                return self._send(200, __import__("json").dumps(ME))
            if p == "/api/auth/status":
                return self._send(200, '{"smtp":true,"dev_email":false,"token_auth":false,"locked":false,"open":false}')
            if p == "/api/voices":
                return self._send(200, '{"voices":[],"default":""}')
            if p == "/api/music":
                return self._send(200, '{"music":[]}')
            if p == "/api/templates":
                return self._send(200, '{"templates":[],"default":""}')
            return self._send(404, '{"error":"stub"}')
        if p == "/" or p == "/index.html":
            html = (POC / "index.html").read_text(encoding="utf-8")
            return self._send(200, html.replace("<head>", '<head><base href="/poc/">', 1), "text/html")
        f = POC / p.lstrip("/").removeprefix("poc/")
        if p.startswith("/poc/"):
            f = POC / p.removeprefix("/poc/")
        if f.is_file():
            ct = "application/javascript" if f.suffix == ".js" else (
                "text/html" if f.suffix == ".html" else "application/octet-stream")
            return self._send(200, f.read_bytes(), ct)
        return self._send(404, "no", "text/plain")

    def log_message(self, *a):
        pass


PORT = int(sys.argv[sys.argv.index("--port") + 1]) if "--port" in sys.argv else 8622
HTTPServer(("127.0.0.1", PORT), H).serve_forever()
