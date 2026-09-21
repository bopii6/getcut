#!/usr/bin/env bash
# 一条命令把线上更新到 GitHub main：拉 → 整包同步 → 写版本戳 → 重启 → 探活，失败自动回滚。
#
# 为什么要有这个脚本（2026-09-21 线上踩完才写的）：
#   · 生产 code/ 一直靠 scp 逐文件传，攒过"server.py 新、agenthub.py 旧"的半新半旧，
#     线上因此挂了约 2 小时（/api/agent/poll 连续 500）。整包同步才有救。
#   · docker restart 不读 --env-file：改了 .env 必须重建容器，所以要 --rebuild。
#   · 版本戳：容器里没有 .git，只能把 sha 写进 BUILD_INFO.json 让它可查。
#
# 用法（在服务器上）：
#   bash /opt/videogen/repo/videogen/tools/deploy_git.sh              # 只同步代码 + 重启
#   bash /opt/videogen/repo/videogen/tools/deploy_git.sh --rebuild    # 改了 .env / 装了新依赖时
set -uo pipefail

BASE=/opt/videogen
REPO=$BASE/repo
CODE=$BASE/code
BRANCH="${VIDEOGEN_DEPLOY_BRANCH:-main}"
REBUILD=0
[ "${1:-}" = "--rebuild" ] && REBUILD=1

cd "$REPO" || { echo "[deploy] 没有 $REPO（先 git clone）"; exit 1; }
export GIT_SSH_COMMAND="ssh -i /root/.ssh/videogen_deploy -o StrictHostKeyChecking=accept-new"
git fetch --depth 50 origin "$BRANCH" || { echo "[deploy] 拉取失败，未做任何改动"; exit 1; }
git reset --hard "origin/$BRANCH" >/dev/null
SHA=$(git rev-parse --short HEAD)
TITLE=$(git log -1 --pretty=%s | cut -c1-72)
echo "[deploy] 目标版本 $SHA 「$TITLE」"

# 改前先留退路：整包备份 + 记录当前 sha
BK="$BASE/backup/git-$SHA-$(date +%H%M%S)"
mkdir -p "$BK" && cp -a "$CODE" "$BK/code" && echo "[deploy] 已备份 -> $BK"

# 整包同步。两类目录区别对待（这就是那 2 小时故障的教训）：
#   · 代码与产物（videogen/、server_static/）必须与 git 一模一样 —— 带 --delete，
#     被删掉的模块要从线上消失（线上现在还剩 overlays/rendernode/subtitle 三个死模块）。
#   · 体积大且含运行时下载内容的（renderer/、assets/、samples/）只前进不删除，
#     免得把不在 git 里的东西（字体、音效、临时素材）扫掉。
for d in videogen server_static; do
  mkdir -p "$CODE/$d"
  rsync -a --delete "$REPO/videogen/$d/" "$CODE/$d/" || { echo "[deploy] 同步 $d 失败"; exit 1; }
  echo "[deploy] 整包同步（含删除）$d"
done
for d in renderer/src assets samples; do
  [ -d "$REPO/videogen/$d" ] || continue
  mkdir -p "$CODE/$d"
  rsync -a "$REPO/videogen/$d/" "$CODE/$d/" || { echo "[deploy] 同步 $d 失败"; exit 1; }
  echo "[deploy] 增量同步（不删）$d"
done
# renderer/src 单独挂进容器，整目录 renderer 也同步了；清掉备份目录残留（不属于受管内容）
rm -rf "$CODE"/videogen.bak-* "$CODE"/videogen/*.bak-* 2>/dev/null

# 版本戳：容器里 /app/videogen 就是这个目录，version.py 会读它
printf '{"sha":"%s","branch":"%s","built":"%s","source":"deploy_git.sh","dirty":false}\n' \
  "$SHA" "$BRANCH" "$(date -Iseconds)" > "$CODE/videogen/BUILD_INFO.json"

if [ "$REBUILD" = 1 ]; then
  echo "[deploy] 重建容器（.env 改动只有重建才生效）"
  bash "$BASE/deploy_new.sh" && exit 0
fi

docker restart videogen >/dev/null 2>&1
for i in $(seq 1 20); do
  sleep 2
  if curl -fsS --max-time 4 http://127.0.0.1:8600/healthz 2>/dev/null | grep -q '"ok":true'; then
    echo "[deploy] 服务正常，线上版本 $SHA"
    echo "[deploy] 回滚命令：cp -a $BK/code/. $CODE/ && docker restart videogen"
    exit 0
  fi
done
echo "[deploy] 探活失败，自动回滚到 $SHA 之前"
cp -a "$BK/code/." "$CODE/"
docker restart videogen >/dev/null 2>&1
sleep 8
docker logs videogen --tail 20
exit 1
