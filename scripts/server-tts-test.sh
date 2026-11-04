#!/bin/bash
cd /tmp
cat > tts.json <<'JSON'
{"text":"这是服务器上的配音测试","voice":"zh-CN-YunxiNeural"}
JSON
echo "请求体:"; cat tts.json; echo
curl -sS --max-time 60 -X POST http://127.0.0.1:8790/api/tts \
  -H 'content-type: application/json' \
  --data-binary @tts.json -o /tmp/out.mp3 -w 'tts: %{http_code}  %{size_download} bytes\n'
file /tmp/out.mp3
