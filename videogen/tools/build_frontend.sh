#!/usr/bin/env bash
# 构建成片台并确认静态 bundle 已同步。
# 只生成到 renderer/browsertool-dist/，不自动改 tracked 文件；部署前若不一致直接阻断。
set -euo pipefail
cd "$(dirname "$0")/.."

echo "[frontend] 构建成片台 bundle"
npm --prefix renderer run build:tool

BUILT="renderer/browsertool-dist/bundle.js"
PUBLISHED="server_static/poc/bundle.js"
if [ ! -f "$BUILT" ] || [ ! -f "$PUBLISHED" ]; then
  echo "[frontend] 缺少构建产物：$BUILT 或 $PUBLISHED" >&2
  exit 1
fi
if ! cmp -s "$BUILT" "$PUBLISHED"; then
  echo "[frontend] bundle 与源码不一致：请把构建产物复制到 $PUBLISHED 并提交后再部署" >&2
  echo "[frontend] 可执行：cp $BUILT $PUBLISHED" >&2
  exit 1
fi
# Remotion 打包会把默认蓝三角 favicon 写进产物：整目录拷过一次，地址栏图标就掉回 Remotion 了
if ! cmp -s renderer/public/favicon.ico server_static/poc/favicon.ico; then
  echo "[frontend] 成片台图标不是品牌方印：cp renderer/public/favicon.ico server_static/poc/favicon.ico" >&2
  exit 1
fi
echo "[frontend] bundle 校验通过"
