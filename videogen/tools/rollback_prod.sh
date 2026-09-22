#!/usr/bin/env bash
# 一键回滚线上到某个提交：bash tools/rollback_prod.sh <短 sha>
#
# 为什么要有这个脚本：以前"回滚"是"人肉去 backup/ 里挑一份、拷回去、看运气"。
# 出事的时候最怕的就是这时候敲错命令 —— 部署脚本每次上线都留了
# /opt/videogen/backup/pre-<sha>-<时间>/code，那就按 sha 找它，别让人去猜。
#
#   bash tools/rollback_prod.sh                 # 不带参数 = 列出可用的回滚点
#   bash tools/rollback_prod.sh 0deed07         # 回到那个提交
set -uo pipefail

# 地址的唯一真身在 deploy/hosts.env（部署/回滚/比对三处共用，别再往这里填 IP）
_HOSTS="$(dirname "$0")/../deploy/hosts.env"
. "$_HOSTS" || { echo "找不到 $_HOSTS —— 地址的唯一真身在 deploy/hosts.env" >&2; exit 1; }
HOST="${VIDEOGEN_DEPLOY_HOST}"
KEY="${VIDEOGEN_DEPLOY_KEY:-$HOME/.ssh/videogen_ecs}"
SHA="${1:-}"
SSH="ssh -i $KEY -o BatchMode=yes"

if [ -z "$SHA" ]; then
  echo "可用的回滚点（最近的在前）："
  $SSH "$HOST" 'cd /opt/videogen && ls -1dt backup/pre-*/ 2>/dev/null | head -12'
  echo "用法：bash tools/rollback_prod.sh <短 sha>"
  exit 0
fi

$SSH "$HOST" "set -e; cd /opt/videogen
src=\$(ls -1dt backup/pre-$SHA-*/code 2>/dev/null | head -1)
if [ -z \"\$src\" ]; then
  echo '没有这个 sha 的备份。现有回滚点：'
  ls -1dt backup/pre-*/ 2>/dev/null | head -8
  exit 1
fi
stamp=\$(date +%Y%m%d-%H%M%S)
cp -a code code.before-rollback-\$stamp          # 回滚本身也要可回退
echo \"当前代码已另存 code.before-rollback-\$stamp\"
rm -rf code/videogen code/server_static code/renderer/src
cp -a \$src/videogen code/videogen
[ -d \$src/server_static ] && cp -a \$src/server_static code/server_static
[ -d \$src/renderer/src ] && cp -a \$src/renderer/src code/renderer/src
docker restart videogen >/dev/null
for i in \$(seq 1 25); do
  sleep 2
  if curl -fsS --max-time 4 http://127.0.0.1:8600/healthz 2>/dev/null | grep -q '\"ok\":true'; then
    echo \"已回滚到 \$src\"
    curl -s http://127.0.0.1:8600/healthz; echo
    exit 0
  fi
done
echo '回滚后探活仍失败，看日志：'
docker logs --tail 20 videogen
exit 1"
