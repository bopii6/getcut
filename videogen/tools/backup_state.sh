#!/usr/bin/env bash
# GetCut 状态备份：把账号/卡密/登记这几个 JSON 打包留一份，滚动保留 N 天。
#
#   用法  backup_state.sh                 打一个新包并清理过期
#         backup_state.sh list            列出现有备份包
#         backup_state.sh verify [包]     校验包能解开（默认最新包）
#         backup_state.sh restore <成员> [包] [目标目录]   从包里取一个文件
#
# 只跑在宿主机（cron 每天 04:30 一次）。容器里以只读方式挂 /opt/videogen/backups，
# 应用读坏了会自己回来找最新包恢复 —— 所以备份目录不需要也不该给应用写权限。
set -euo pipefail

BASE="${VIDEOGEN_BASE:-/opt/videogen}"          # 部署根目录
DEST="${VIDEOGEN_BACKUPS:-$BASE/backups}"       # 备份包存放处（不在工作区里）
KEEP="${VIDEOGEN_BACKUP_KEEP:-90}"              # 保留多少天
STAMP="$(date +%Y%m%d-%H%M%S)"

# 要备的东西：相对 BASE 的路径。少一个就跳过（本机开发/新装机器可能还没有）。
# 密钥三件套：2026-09-21 起生产放在工作区之外的 state/（本机开发仍落在 data/，
# 所以下面两行路径都留着 —— 存在哪个备哪个，两条都不存在时上面的空检查会退出。
ITEMS=(
  state/.videogen-users.json       # 账号 + 谁买了哪一档：丢了等于客户名单归零
  state/.videogen-licenses.json    # 卡密：已发/未发都在这
  state/.videogen-auth-secret      # 会话签名密钥：丢了所有人重登
  state/.videogen-brand            # 品牌套装（生产位置）
  data/.videogen-users.json
  data/.videogen-licenses.json
  data/.videogen-auth-secret
  data/.videogen-try.json          # 试玩额度账本
  data/bundles.json                # 素材包归属
  data/.videogen-brand             # 品牌套装（logo / 水印 / 术语表）
  registry.json                    # 项目与成片登记：丢了作品库变空壳
  jobs.json                        # 任务表
)

have=()
for it in "${ITEMS[@]}"; do
  [ -e "$BASE/$it" ] && have+=("$it")
done
if [ ${#have[@]} -eq 0 ]; then
  echo "[backup] $BASE 下没有任何状态文件，跳过" >&2
  exit 0
fi

mkdir -p "$DEST"
chmod 700 "$DEST"

cmd="${1:-run}"
newest() { ls -1t "$DEST"/videogen-data-*.tar.gz 2>/dev/null | head -1 || true; }

case "$cmd" in
  list)
    ls -lh "$DEST"/videogen-data-*.tar.gz 2>/dev/null || echo "[backup] 还没有备份包"
    ;;
  verify)
    pack="${2:-$(newest)}"
    [ -n "$pack" ] || { echo "[backup] 没有可校验的包" >&2; exit 1; }
    tar tzf "$pack" >/dev/null
    echo "[backup] 可解开: $(basename "$pack")"
    tar tzf "$pack" | sed 's/^/    /'
    ;;
  restore)
    member="${2:?要恢复哪个文件，例如 data/.videogen-users.json}"
    pack="${3:-$(newest)}"
    out="${4:-/tmp/restore-$STAMP}"
    [ -n "$pack" ] || { echo "[backup] 没有备份包" >&2; exit 1; }
    mkdir -p "$out"; chmod 700 "$out"
    tar xzf "$pack" -C "$out" "$member"
    echo "[backup] 已取到 $out/$member（确认无误后再手工放回 $BASE/$member）"
    ;;
  run)
    pack="$DEST/videogen-data-$STAMP.tar.gz"
    tmp="$pack.tmp"
    tar czf "$tmp" -C "$BASE" "${have[@]}"
    # 落盘 + 当场校验：解不开的备份不是备份
    sync
    tar tzf "$tmp" >/dev/null
    mv "$tmp" "$pack"
    chmod 600 "$pack"
    size=$(du -h "$pack" | cut -f1)
    # 滚动清理：只按天数删。真删掉了东西且剩得太少才告警（第一次跑只有一个包，不是异常）
    mapfile -d '' -t stale < <(find "$DEST" -maxdepth 1 -name 'videogen-data-*.tar.gz' \
                                 -mtime +"$KEEP" -print0)
    for f in "${stale[@]}"; do
      rm -f "$f" && echo "[backup] 过期删除 $(basename "$f")"
    done
    left=$(ls -1 "$DEST"/videogen-data-*.tar.gz 2>/dev/null | wc -l)
    if [ "${#stale[@]}" -gt 0 ] && [ "$left" -lt 3 ]; then
      echo "[backup] ⚠ 清理后只剩 $left 个包，请检查 KEEP 配置（当前 $KEEP 天）" >&2
    fi
    echo "[backup] 完成 $pack ($size, 共 $left 个包, 保留 $KEEP 天)"
    ;;
  *)
    echo "用法: $0 [run|list|verify|restore <成员> [包] [目标]]" >&2
    exit 2
    ;;
esac
