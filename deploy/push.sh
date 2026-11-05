#!/usr/bin/env bash
# 把出片服务推到服务器（在本地项目根目录跑）
#   GETCUT_HOST=root@115.190.113.128 bash deploy/push.sh
#   GETCUT_HOST=root@115.190.113.128 bash deploy/push.sh --install   # 顺手安装
#
# 只传运行必需的文件，不传 node_modules、不传 remotion、不传 665MB 的 broll。
set -euo pipefail

HOST="${GETCUT_HOST:-}"
TARGET="${GETCUT_TARGET:-/opt/getcut-render}"
if [ -z "$HOST" ]; then
  echo "用法：GETCUT_HOST=root@你的IP bash deploy/push.sh"
  exit 1
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."

FILES=(
  server/api.mjs
  server/jobs.mjs
  server/render.mjs
  server/audio.mjs
  server/fonts.mjs
  server/.build/draw.mjs
  lib/env.mjs
  lib/tts.mjs
  scripts/plan.mjs
  public/fonts
  deploy/package.json
  deploy/getcut-render.service
  deploy/install.sh
)

if [ -f .env ]; then
  FILES+=(.env)
  echo "· 会一起传 .env（含 API key）"
fi

echo "· 打包上传到 $HOST:$TARGET"
tar czf - "${FILES[@]}" \
  | ssh "$HOST" "mkdir -p $TARGET && tar xzf - -C $TARGET \
      && mv -f $TARGET/deploy/package.json $TARGET/package.json \
      && mv -f $TARGET/deploy/getcut-render.service $TARGET/getcut-render.service \
      && mv -f $TARGET/deploy/install.sh $TARGET/install.sh \
      && rmdir $TARGET/deploy 2>/dev/null || true"

echo "· 上传完成"

if [ "${1:-}" = "--install" ]; then
  echo "· 在服务器上执行安装"
  ssh "$HOST" "cd $TARGET && bash install.sh"
else
  echo "· 下一步：ssh $HOST 'cd $TARGET && bash install.sh'"
fi
