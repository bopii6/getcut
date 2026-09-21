#!/usr/bin/env bash
# 一条命令把线上更新到 GitHub main —— 在你这台电脑上跑（不是服务器上）。
#
# 为什么是"推"不是服务器上"拉"（2026-09-21 夜实测）：
#   · 服务器到 GitHub 的浅克隆卡在 4.1M 不动，还会留后台进程互相挖墙角 → 那台机不适合
#     自己 git pull；本机 scp/rsync 到服务器一直是通的。
#   · 只送 **已提交的 HEAD**（git archive），不送工作树 —— 工作树里可能混着别的会话
#     未提交的改动，那种"顺手一起上线"迟早出事。
#   · 整包同步，不再逐文件拷：上一版逐文件传攒出过"server.py 新、agenthub.py 旧"，
#     线上挂了约 2 小时。
#   · 版本戳写进 BUILD_INFO.json（容器里没有 .git，不写就只能手填、或者查不到）。
#
# 用法：
#   bash tools/deploy_to_prod.sh --check          # 只报告线上与 HEAD 的差异，不改任何东西
#   bash tools/deploy_to_prod.sh                  # 同步 + 重启 + 探活（失败自动回滚）
#   bash tools/deploy_to_prod.sh --rebuild        # 改了 .env / 加依赖时（重建容器才读 env-file）
set -uo pipefail

HOST="${VIDEOGEN_DEPLOY_HOST:-root@152.136.119.62}"
KEY="${VIDEOGEN_DEPLOY_KEY:-$HOME/.ssh/videogen_ecs}"
BASE=/opt/videogen
SSH="ssh -i $KEY -o BatchMode=yes"
RS="rsync -az --human-readable -e ssh"
RSH="ssh -i $KEY -o BatchMode=yes"

MODE=deploy; REBUILD=0
for a in "$@"; do
  case "$a" in
    --check) MODE=check ;;
    --rebuild) REBUILD=1 ;;
    *) echo "不认识的参数：$a（可用 --check / --rebuild）" >&2; exit 2 ;;
  esac
done

cd "$(dirname "$0")/.." || exit 1
SHA=$(git rev-parse --short HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
TITLE=$(git log -1 --pretty=%s | cut -c1-70)
echo "[deploy] 要上线的版本：$BRANCH @ $SHA 「$TITLE」"

# 闸门不过就别上线（这条是整轮评审的意义所在）
if [ "$MODE" = deploy ]; then
  if ! bash tools/selfcheck.sh >/tmp/selfcheck.log 2>&1; then
    echo "[deploy] 门禁没过，先别上线"; tail -8 /tmp/selfcheck.log; exit 1
  fi
  echo "[deploy] 门禁全绿"
fi

STAGE=$(mktemp -d 2>/dev/null || echo /tmp/vg-stage-$$)
rm -rf "$STAGE"; mkdir -p "$STAGE"
# git archive：只导出提交进库的内容（不含工作树里未提交的改动、不含 .git）
git -C .. archive --format=tar "$SHA" | tar -x -C "$STAGE" || { echo "[deploy] 导出 HEAD 失败"; exit 1; }
SRC="$STAGE/videogen"
[ -d "$SRC/videogen" ] || { echo "[deploy] 导出结构不对（找 $SRC/videogen）"; exit 1; }

drift() {  # 线上有、这次要送的版本里没有 → 只报告，不擅自删
  local d="$1"
  $SSH "$HOST" "cd $BASE/code/$d 2>/dev/null && find . -type f -printf '%P\n'" 2>/dev/null | sort > /tmp/remote-$d.txt
  (cd "$SRC/$d" 2>/dev/null && find . -type f -printf '%P\n' | sort > /tmp/local-$d.txt) || : > /tmp/local-$d.txt
  local only
  only=$(comm -23 /tmp/remote-$d.txt /tmp/local-$d.txt | head -25)
  if [ -n "$only" ]; then
    echo "  [$d] 线上独有、这次不动它（$(comm -23 /tmp/remote-$d.txt /tmp/local-$d.txt | wc -l) 个）:"
    echo "$only" | sed 's/^/      /'
  fi
}

echo "[deploy] 线上与 HEAD 的差异（左=只在线上，右=只在这版）"
for d in videogen server_static renderer/src assets samples; do
  $SSH "$HOST" "test -d $BASE/code/$d" || { echo "  [$d] 线上没有这个目录，跳过"; continue; }
  out=$($RS -n --out-format='%n' -e "$RSH" "$SRC/$d/" "$HOST:$BASE/code/$d/" 2>/dev/null | grep -v '^$' | head -20)
  [ -n "$out" ] && { echo "  [$d] 要更新:"; echo "$out" | sed 's/^/      /'; }
  [ "$MODE" = check ] && drift "$d"
done
if [ "$MODE" = check ]; then
  echo "[check] 只报告，什么都没改。要上线去掉 --check。"
  rm -rf "$STAGE"; exit 0
fi

echo "[deploy] 改前备份整包"
BK="$BASE/backup/pre-$SHA-$(date +%H%M%S)"
$SSH "$HOST" "mkdir -p $BK && cp -a $BASE/code $BK/code && cp -a $BASE/.env $BK/env && echo '  备份 -> $BK'"

for d in videogen server_static; do          # 代码与前端产物：整包对齐
  $RS -e "$RSH" "$SRC/$d/" "$HOST:$BASE/code/$d/" || { echo "[deploy] 传 $d 失败"; exit 1; }
done
for d in renderer/src assets samples; do     # 体积大、可能含运行时内容：只前进不删
  [ -d "$SRC/$d" ] && $RS -e "$RSH" "$SRC/$d/" "$HOST:$BASE/code/$d/"
done

printf '{"sha":"%s","branch":"%s","built":"%s","source":"deploy_to_prod.sh","dirty":false}\n' \
  "$SHA" "$BRANCH" "$(date -Iseconds)" > /tmp/BUILD_INFO.json
$RS -e "$RSH" /tmp/BUILD_INFO.json "$HOST:$BASE/code/videogen/BUILD_INFO.json"

if [ "$REBUILD" = 1 ]; then
  echo "[deploy] 重建容器（.env 改动只有重建才生效）"
  $SSH "$HOST" "cd $BASE && bash deploy_new.sh" | tail -6
  rm -rf "$STAGE"; exit 0
fi

echo "[deploy] 重启并探活"
$SSH "$HOST" "docker restart videogen >/dev/null 2>&1
ok=0
for i in \$(seq 1 25); do sleep 2; curl -fsS --max-time 4 http://127.0.0.1:8600/healthz 2>/dev/null | grep -q '\"ok\":true' && { ok=1; break; }; done
if [ \$ok != 1 ]; then echo '[deploy] 探活失败，回滚'; cp -a $BK/code/. $BASE/code/; cp -a $BK/env $BASE/.env; docker restart videogen >/dev/null 2>&1; sleep 6; docker logs videogen --tail 15; exit 1; fi
echo '[deploy] 服务正常'
curl -s http://127.0.0.1:8600/healthz; echo
docker exec videogen cat $BASE/code/videogen/BUILD_INFO.json 2>/dev/null | head -c 160; echo"
rc=$?
rm -rf "$STAGE" /tmp/BUILD_INFO.json
[ $rc -eq 0 ] && echo "[deploy] 完成。回滚：ssh 到服务器执行  cp -a $BK/code/. $BASE/code/ && docker restart videogen"
exit $rc
