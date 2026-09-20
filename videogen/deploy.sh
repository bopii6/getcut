#!/usr/bin/env bash
# videogen 云主机一键部署
#   bash deploy.sh              # 自动：有镜像则拉取，否则本地构建
#   bash deploy.sh --build      # 强制在主机上构建
#   bash deploy.sh --pull       # 强制从 GHCR 拉取（需先 docker login ghcr.io）
set -euo pipefail

IMAGE="ghcr.io/bopii6/videogen:latest"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

MODE="auto"
[[ "${1:-}" == "--build" ]] && MODE="build"
[[ "${1:-}" == "--pull"  ]] && MODE="pull"

log() { printf '\033[36m[videogen]\033[0m %s\n' "$*"; }
die() { printf '\033[31m[videogen] 失败：%s\033[0m\n' "$*" >&2; exit 1; }

# ---------- 1. Docker ----------
if ! command -v docker >/dev/null 2>&1; then
  log "未检测到 Docker，开始安装（国内源）…"
  curl -fsSL https://get.docker.com | sh || die "Docker 安装失败，请手动安装后重试"
  systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || die "需要 docker compose v2（docker-compose-plugin）"

# ---------- 2. .env ----------
if [[ ! -f .env ]]; then
  cp .env.example .env
  log "已生成 .env，请填写密钥后重新运行本脚本："
  log "  vi $DIR/.env   # DEEPSEEK_API_KEY 必填，其余可留空"
  exit 1
fi
grep -q '^DEEPSEEK_API_KEY=..*' .env || die ".env 里 DEEPSEEK_API_KEY 为空（没有它无法做分镜/文案）"

# 访问令牌：没有就自动生成一份。工作台首次打开时会要你输入一次。
if ! grep -q '^VIDEOGEN_TOKEN=..*' .env; then
  TOKEN="vg-$(od -An -N8 -tx4 /dev/urandom | tr -d ' \n')"
  # 删除旧行（可能是空值）再追加
  sed -i '/^VIDEOGEN_TOKEN=/d' .env
  printf '\n# 工作台访问令牌（自动生成，打开页面时输入一次即可）\nVIDEOGEN_TOKEN=%s\n' "$TOKEN" >> .env
  log "已生成访问令牌 VIDEOGEN_TOKEN=$TOKEN"
fi

# ---------- 3. 取镜像 ----------
pull_image() {
  log "拉取镜像 $IMAGE"
  docker pull "$IMAGE"
}

if [[ "$MODE" == "pull" ]]; then
  pull_image
elif [[ "$MODE" == "auto" ]]; then
  if ! pull_image 2>/dev/null; then
    log "拉取失败（多为网络/未登录 GHCR），改为在主机上构建"
    MODE="build"
  fi
fi

# ---------- 4. 启动 ----------
if [[ "$MODE" == "build" ]]; then
  log "本地构建镜像（装 Python 依赖 + ffmpeg；画面渲染在客户浏览器里，镜像内不再有 Node/Chrome）"
  export DOCKER_BUILDKIT=1
  # 国内网络加速（可按需改成官方源）
  export NPM_CONFIG_REGISTRY="${NPM_CONFIG_REGISTRY:-https://registry.npmmirror.com}"
  docker compose build \
    --build-arg NPM_CONFIG_REGISTRY="$NPM_CONFIG_REGISTRY" \
    || die "构建失败"
fi

log "启动服务"
docker compose up -d

# ---------- 5. 健康检查 ----------
log "等待 /healthz …"
for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8600/healthz" >/dev/null 2>&1; then
    IP="$(curl -fsS --max-time 5 https://api.ipify.org || echo '<服务器IP>')"
    log "部署完成：http://${IP}:8600"
    log "日志：docker compose logs -f"
    exit 0
  fi
  sleep 2
done

docker compose logs --tail 40
die "服务未在 60 秒内就绪，请查看上面的日志"
