#!/usr/bin/env bash
# 比对「仓库里那份 Caddyfile」与「服务器上正在生效的那份」是否一致。
#
# 为什么要这个：反代配置一直只躺在服务器 /etc/caddy/Caddyfile，仓库里那份是抄本。
# 换机、重装、误删时没人知道线上到底怎么配的（压缩开没开、转发头怎么给、绑哪几个域名），
# 而这些直接决定"客户打开首页要下多少字节"和"限流认不认得真 IP"。
#
# 用法：bash tools/caddy_check.sh          # 只比对
#      bash tools/caddy_check.sh --push  # 把仓库这份装到服务器（备份后 reload，不重启 caddy）
set -uo pipefail
cd "$(dirname "$0")/.."

HOST="${VIDEOGEN_DEPLOY_HOST:-root@152.136.119.62}"
KEY="${VIDEOGEN_DEPLOY_KEY:-$HOME/.ssh/videogen_ecs}"
SSH="ssh -i $KEY -o BatchMode=yes"
REMOTE=/etc/caddy/Caddyfile
LOCAL=deploy/Caddyfile

[ -f "$LOCAL" ] || { echo "仓库里没有 $LOCAL"; exit 1; }
$SSH "$HOST" "cat $REMOTE" 2>/dev/null | sed 's/[[:space:]]*$//' > /tmp/caddy-live.txt \
  || { echo "连不上 $HOST，或没权限读 $REMOTE"; exit 1; }
sed 's/[[:space:]]*$//' "$LOCAL" > /tmp/caddy-repo.txt

if diff -u /tmp/caddy-repo.txt /tmp/caddy-live.txt > /tmp/caddy-diff.txt; then
  echo "一致：仓库 $LOCAL 就是线上生效的那份"
  exit 0
fi
echo "不一致（左=仓库 右=线上生效）："
sed -n '1,40p' /tmp/caddy-diff.txt
if [ "${1:-}" != "--push" ]; then
  echo; echo "确认哪边对之后：仓库对就 --push；线上对就把线上那份抄回 $LOCAL"
  exit 1
fi
echo "--push：先备份线上那份，再装仓库这份，然后校验语法并 reload"
$SSH "$HOST" "cp -a $REMOTE $REMOTE.bak-\$(date +%Y%m%d-%H%M%S)" \
  && cat "$LOCAL" | $SSH "$HOST" "cat > $REMOTE" \
  && $SSH "$HOST" "caddy validate --config $REMOTE --adapter caddyfile >/dev/null 2>&1 && systemctl reload caddy && echo '已生效'" \
  || { echo "校验没过，没敢 reload"; exit 1; }
