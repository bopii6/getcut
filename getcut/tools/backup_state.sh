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

BASE="${GETCUT_BASE:-/opt/videogen}"          # 部署根目录
DEST="${GETCUT_BACKUPS:-$BASE/backups}"       # 备份包存放处（不在工作区里）
KEEP="${GETCUT_BACKUP_KEEP:-90}"              # 保留多少天
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

mirror_guard() {  # 镜像前看一眼余量：正本一半大 + 至少 1G，不够就别动
  local src="$1" avail need
  command -v rsync >/dev/null 2>&1 || { echo "[backup] ⚠ 没有 rsync，跳过大件镜像" >&2; return 1; }
  avail=$(df -k "$DEST" | awk 'NR==2 {print $4}')
  need=$(du -sk "$src" | awk '{print $1}')
  [ "$avail" -gt $((need / 2 + 1048576)) ]
}

mirror_big_files() {  # 大件镜像（2026-09-24 起）：成片与素材包不进上面的 tar ——
                      # 一天一份 tar 会把盘吃光，rsync 只拷增量。
                      # ⚠️ 与正本同盘：防误删、防写坏，不防整盘故障；整机级
                      # 备份要另走云存储（TODO，盘富余前先这样顶着）。
  # 成片：客户付过钱的交付物，云端没有底片（片子在客户浏览器里渲的）。
  # 不加 --delete：正本被误删后镜像还在 —— 删除不该被备份同步过去。
  if [ -d "$BASE/outputs" ] && mirror_guard "$BASE/outputs"; then
    mkdir -p "$DEST/outputs-mirror"; chmod 700 "$DEST/outputs-mirror"
    rsync -a "$BASE/outputs/" "$DEST/outputs-mirror/"
    echo "[backup] 成片镜像完成 $(du -sh "$DEST/outputs-mirror" | cut -f1)"
  fi
  # 素材包：客户传上来的原始材料，丢了要客户重传。加 --delete：源头清掉的
  # 死包镜像跟着清，不让镜像单方面膨胀。收件区是 24h 过期的临时票，不备。
  if [ -d "$BASE/data" ] && mirror_guard "$BASE/data"; then
    mkdir -p "$DEST/bundles-mirror"; chmod 700 "$DEST/bundles-mirror"
    rsync -a --delete --exclude='.intakes' "$BASE/data/" "$DEST/bundles-mirror/"
    echo "[backup] 素材包镜像完成 $(du -sh "$DEST/bundles-mirror" | cut -f1)"
  fi
}

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
    mirror_big_files
    ;;
  *)
    echo "用法: $0 [run|list|verify|restore <成员> [包] [目标]]" >&2
    exit 2
    ;;
esac
