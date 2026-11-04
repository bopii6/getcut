#!/bin/bash
echo "== which node =="
which node || true
command -v node || true
ls -l $(command -v node) 2>/dev/null || true
/usr/bin/node -v 2>&1 | head -2 || true
echo "== pip =="
python3 -m pip --version 2>&1 | head -2
echo "== net =="
curl -sS -o /dev/null -w "pypi:%{http_code}\n" https://pypi.org/simple/ --max-time 10 || echo "pypi fail"
echo "== systemd =="
systemctl --version | head -1
echo "== caddy file =="
ls -l /etc/caddy/Caddyfile
