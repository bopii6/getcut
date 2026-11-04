#!/usr/bin/env bash
# 渲染工人节点 · 新机器一次性引导（在节点上以 root 运行）
#   bash _node_setup.sh                          # 主站 IP 取 deploy/hosts.env 的默认值
#   MAIN_IP=10.0.0.1 bash _node_setup.sh         # 临时指另一台
# 干的事：装 docker（国内源）→ 建目录 → 防火墙只放行主站 IP 访问 9700（开机自动重放）
set -euo pipefail

# 主站 IP 的唯一真身在 deploy/hosts.env（与部署/回滚脚本同一份，别再往这里填 IP）
_HOSTS="$(dirname "$0")/deploy/hosts.env"
. "$_HOSTS" || { echo "找不到 $_HOSTS —— 主站 IP 的唯一真身在 deploy/hosts.env" >&2; exit 1; }
MAIN_IP="${MAIN_IP:-$GETCUT_MAIN_IP}"
log() { printf '\033[36m[node]\033[0m %s\n' "$*" >&2; }
die() { printf '\033[31m[node] 失败：%s\033[0m\n' "$*" >&2; exit 1; }

# ---------- docker ----------
if ! command -v docker >/dev/null 2>&1; then
  log "安装 docker（国内源）…"
  curl -fsSL "https://get.docker.com" | sh
  systemctl enable --now docker
fi
docker compose version >/dev/null 2>&1 || die "需要 docker compose v2"

# ---------- 目录 ----------
mkdir -p /opt/videogen-node/code

# ---------- 防火墙：9700 只许主站来 ----------
FWUNIT=/etc/systemd/system/rendernode-fw.service
cat > "$FWUNIT" <<EOF
[Unit]
Description=rendernode: port 9700 only from main server
After=network-pre.target
Before=network.target

[Service]
Type=oneshot
ExecStart=/bin/sh -c '/usr/sbin/iptables -C INPUT -p tcp --dport 9700 ! -s ${MAIN_IP} -j DROP 2>/dev/null || /usr/sbin/iptables -I INPUT -p tcp --dport 9700 ! -s ${MAIN_IP} -j DROP'

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now rendernode-fw.service
log "防火墙规则已上：9700 只放行 ${MAIN_IP}"

# ---------- 镜像 ----------
if ! docker image inspect videogen:latest >/dev/null 2>&1; then
  log "节点上还没有 videogen:latest 镜像——从主站传："
  log "  ssh 主站 'docker save videogen:latest | gzip -1' | gunzip | docker load"
fi
log "引导完成。下一步：放好 .env（RENDERNODE_TOKEN）与 docker-compose.node.yml、同步 code/，然后 compose up"
