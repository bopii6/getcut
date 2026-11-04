#!/bin/bash
set -e
cat > /etc/systemd/system/getcut-api.service <<'UNIT'
[Unit]
Description=GetCut API proxy (plan + tts)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/getcut/api
Environment=GETCUT_PROXY_PORT=8790
ExecStart=/usr/bin/node proxy.mjs
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable getcut-api >/dev/null 2>&1 || true
systemctl restart getcut-api
sleep 2
systemctl is-active getcut-api
echo "--- health ---"
curl -sS --max-time 10 http://127.0.0.1:8790/api/health || echo "健康检查失败"
echo
echo "--- plan ---"
curl -sS --max-time 60 -X POST http://127.0.0.1:8790/api/plan \
  -H 'content-type: application/json' \
  -d '{"text":"想开一家小店，你最怕的是什么？不是没客人，是钱投进去三个月就撑不住。第一个数，前期总投入。把品牌名发给我，我帮你算一遍。"}' | head -c 400
echo
echo "--- tts ---"
curl -sS --max-time 60 -X POST http://127.0.0.1:8790/api/tts \
  -H 'content-type: application/json' -d '{"text":"测试一下配音"}' -o /tmp/t.mp3 -w "tts:%{http_code} %{size_download} bytes\n"
