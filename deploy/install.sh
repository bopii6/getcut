#!/usr/bin/env bash
# GetCut 出片服务 · 服务器端安装脚本
# 用法：bash install.sh        （在 /opt/getcut-render 目录里跑，root 权限）
#
# 做的事：补齐 ffmpeg / python3 / edge-tts / 中文字体 → 装 node 依赖
#        → 注册 systemd 服务 → 起在 127.0.0.1:8902
# 不做的事：不碰 Caddy 配置，不动已有的 Web 端服务。
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${GETCUT_API_PORT:-8902}"

say() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()  { printf '   ✓ %s\n' "$1"; }
bad() { printf '   ✗ %s\n' "$1"; }

say "1/6 检查 Node"
if ! command -v node >/dev/null 2>&1; then
  bad "没找到 node，先装 Node 18 以上（推荐 20）"
  exit 1
fi
NODE_MAJOR="$(node -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 18 ]; then
  bad "node 版本 $(node -v) 太低，至少要 18"
  exit 1
fi
ok "node $(node -v)"

say "2/6 检查 ffmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
  ok "$(ffmpeg -version 2>/dev/null | head -1)"
else
  echo "   没装，开始安装…"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get update -qq && apt-get install -y -qq ffmpeg
  elif command -v yum >/dev/null 2>&1; then
    yum install -y ffmpeg || {
      bad "yum 源里没有 ffmpeg，需要装 EPEL 或换成静态编译版"
      exit 1
    }
  else
    bad "不认识这个发行版的包管理器，请手动装 ffmpeg"
    exit 1
  fi
  ok "$(ffmpeg -version 2>/dev/null | head -1)"
fi

say "3/6 检查 python3 + edge-tts"
if ! command -v python3 >/dev/null 2>&1; then
  if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y -qq python3 python3-pip
  else
    yum install -y python3 python3-pip
  fi
fi
if python3 -c 'import edge_tts' >/dev/null 2>&1; then
  ok "edge-tts 已就绪（$(python3 -c 'import edge_tts,sys;print(sys.version.split()[0])')）"
else
  echo "   装 edge-tts…"
  python3 -m pip install --upgrade pip >/dev/null 2>&1 || true
  python3 -m pip install --upgrade edge-tts 2>/dev/null \
    || python3 -m pip install --upgrade --break-system-packages edge-tts \
    || { bad "edge-tts 装不上，配音会失败"; exit 1; }
  ok "edge-tts 装好了"
fi

say "4/6 检查中文字体"
# 缺字体不会报错，只会让整片中文变成方框，所以必须显式验证
FONT_OK=0
if [ -f "$APP_DIR/public/fonts/SourceHanSansCN-Heavy.otf" ]; then
  ok "自带字体在（$(du -h "$APP_DIR/public/fonts" | cut -f1)）"
  FONT_OK=1
else
  echo "   自带字体缺失，尝试装系统字体…"
  if command -v apt-get >/dev/null 2>&1; then
    apt-get install -y -qq fonts-noto-cjk && FONT_OK=1
  elif command -v yum >/dev/null 2>&1; then
    yum install -y google-noto-sans-cjk-ttc-fonts && FONT_OK=1
  fi
fi
[ "$FONT_OK" = "1" ] || { bad "没有中文字体，出片会是满屏方框"; exit 1; }

say "5/6 装 node 依赖"
cd "$APP_DIR"
if [ ! -f package.json ]; then
  bad "package.json 不在 $APP_DIR，先跑 push.sh 把文件推上来"
  exit 1
fi
npm install --omit=dev --no-audit --no-fund 2>&1 | tail -3
ok "@napi-rs/canvas $(node -p "require('./node_modules/@napi-rs/canvas/package.json').version" 2>/dev/null || echo '已安装')"

if [ ! -f "$APP_DIR/.env" ]; then
  bad "缺 .env（DEEPSEEK_API_KEY / PEXELS_API_KEY），拆稿和抓空镜会退化成规则版"
fi

say "6/6 注册 systemd 服务"
NODE_BIN="$(command -v node)"
install -m 644 "$APP_DIR/getcut-render.service" /etc/systemd/system/getcut-render.service
sed -i "s#ExecStart=.*#ExecStart=$NODE_BIN server/api.mjs#" /etc/systemd/system/getcut-render.service
systemctl daemon-reload
systemctl enable getcut-render >/dev/null 2>&1
systemctl restart getcut-render
sleep 3

if curl -fsS "http://127.0.0.1:$PORT/v1/health" >/dev/null 2>&1; then
  ok "服务已起来：http://127.0.0.1:$PORT/v1/health"
  curl -s "http://127.0.0.1:$PORT/v1/health"; echo
else
  bad "服务没起来，看日志：journalctl -u getcut-render -n 50 --no-pager"
  exit 1
fi

cat <<'TIP'

--------------------------------------------------------------------
下一步（手动，别漏）：
  1. 在现有 Caddyfile 的站点块里加一行反向代理：

       handle /v1/* {
           reverse_proxy 127.0.0.1:8902
       }

     放好位置后 reload：  systemctl reload caddy
  2. 验证：  curl https://你的域名/v1/health
  3. 小程序真机要求 HTTPS + 已备案域名，IP 地址不行。
--------------------------------------------------------------------
TIP
