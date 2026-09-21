#!/usr/bin/env bash
# videogen 更新脚本 v2：配置改用 /opt/videogen/.env（--env-file），改 env 只需编辑该文件后重跑本脚本
set -euo pipefail
cd /opt/videogen

# 首次：从现有容器导出环境变量到 .env
if [ ! -f .env ]; then
  docker inspect videogen --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -E '^(DEEPSEEK_API_KEY|ZHIPU_API_KEY|ALIYUN_ACCESS_KEY|PEXELS_API_KEY|PIXABAY_API_KEY|VIDEOGEN_TOKEN|VIDEOGEN_DEV_EMAIL|VIDEOGEN_WORKSPACE|HOST|PORT|EMAIL_)' > .env
  cat >> .env << 'E2'
# 发信邮箱（注册验证码）：填好后重跑本脚本生效
EMAIL_SMTP_HOST=
EMAIL_SMTP_PORT=465
EMAIL_SMTP_USER=
EMAIL_SMTP_PASS=
EMAIL_FROM=
E2
  echo "[deploy] 已生成 .env"
fi

# 代码备份
BK="backup/code-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK/videogen" "$BK/server_static"
cp -a code/videogen/*.py "$BK/videogen/"
cp -a code/server_static/index.html "$BK/server_static/" 2>/dev/null || true
echo "[deploy] 旧代码已备份 -> $BK"

# 重建容器（先停旧的再改名，避免端口占用）
docker stop videogen >/dev/null
docker rm -f videogen-old >/dev/null 2>&1 || true
docker rename videogen videogen-old
docker run -d --name videogen --restart unless-stopped --network host \
  --env-file .env \
  -v /opt/videogen/data:/data \
  -v /opt/videogen/jobs.json:/app/jobs.json \
  -v /opt/videogen/outputs:/app/outputs \
  -v /opt/videogen/registry.json:/app/registry.json \
  -v /opt/videogen/code/server_static:/app/server_static \
  -v /opt/videogen/code/videogen:/app/videogen \
  -v /opt/videogen/code/renderer/src:/app/renderer/src \
  -v /opt/videogen/code/assets:/app/assets \
  -v /opt/videogen/state:/state \
  -v /opt/videogen/backups:/opt/videogen/backups:ro \
  -v /opt/videogen/code/samples:/app/samples \
  -v /opt/videogen/renderer-media:/app/renderer/public/media \
  videogen:latest >/dev/null

docker exec videogen pip install -q "websockets>=14" "cos-python-sdk-v5>=1.9.3" >/dev/null 2>&1 || true

for i in $(seq 1 20); do
  sleep 2
  if curl -fsS --max-time 4 http://127.0.0.1:8600/healthz 2>/dev/null | grep -q '"ok":true'; then
    echo "[deploy] 服务正常（新容器已就绪，旧容器保留为 videogen-old 可回滚）"
    exit 0
  fi
done
echo "[deploy] 失败，回滚"
docker rm -f videogen >/dev/null 2>&1 || true
docker rename videogen-old videogen
docker start videogen >/dev/null
docker logs videogen --tail 20
exit 1
