#!/bin/bash
set -e
echo "== 目录 =="
mkdir -p /opt/getcut/web /opt/getcut/api/scripts /opt/getcut/api/lib
echo "== 装 edge-tts =="
python3 -m pip install --quiet --upgrade edge-tts 2>&1 | tail -3
python3 -c "import edge_tts; print('edge-tts ok')"
echo "== 磁盘 =="
df -h / | tail -1
