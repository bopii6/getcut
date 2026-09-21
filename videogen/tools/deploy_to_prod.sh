#!/usr/bin/env bash
# 一条命令把线上更新到 GitHub main —— 在你这台电脑上跑（不是服务器上）。
#
# 为什么是"推"不是服务器上"拉"（2026-09-21 夜实测）：
#   · 服务器到 GitHub 的浅克隆卡在 4.1M 不动，还会留后台进程互相挖墙角 → 那台机不适合
#     自己 git pull；本机 tar/scp 到服务器一直是通的（Git Bash 里没有 rsync，所以脚本不依赖它）。
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
# 文本文件归一成 LF：Windows 侧导出的 CRLF 会让每一行都"变了"，
# 比对与回滚都会被这种假差异带偏（二进制原样不动）。
find "$SRC" -type f \( -name '*.py' -o -name '*.js' -o -name '*.mjs' -o -name '*.css'   -o -name '*.html' -o -name '*.json' -o -name '*.md' -o -name '*.txt' -o -name '*.ts' -o -name '*.tsx' \)   -print0 | xargs -0 -r sed -i 's/
$//'
echo "[deploy] 文本已归一为 LF"

drift() {  # 线上有、这次要送的版本里没有 → 只报告，不擅自删（缓存类就在这堆里）
  local d="$1" tag only n
  tag=$(printf '%s' "$d" | tr '/' '_')        # renderer/src 这种带斜杠的名字不能直接当文件名
  $SSH "$HOST" "cd $BASE/code/$d 2>/dev/null && find . -type f -printf '%P\n'" 2>/dev/null | sort > "/tmp/remote-$tag.txt"
  (cd "$SRC/$d" 2>/dev/null && find . -type f -printf '%P\n') | sort > "/tmp/local-$tag.txt"
  only=$(comm -23 "/tmp/remote-$tag.txt" "/tmp/local-$tag.txt" | head -25)
  n=$(comm -23 "/tmp/remote-$tag.txt" "/tmp/local-$tag.txt" | wc -l)
  if [ "$n" -gt 0 ]; then
    echo "  [$d] 线上独有 $n 个，这次不动它们:"
    echo "$only" | sed 's/^/      /'
  fi
}

echo "[deploy] 线上与 HEAD 的差异（按 路径+字节 比，MISSING=只有一边有）"
for d in videogen server_static renderer/src assets samples; do
  $SSH "$HOST" "test -d $BASE/code/$d" || { echo "  [$d] 线上没有这个目录"; continue; }
  tag=$(printf '%s' "$d" | tr '/' '_')
  (cd "$SRC/$d" && find . -type f -printf '%P %s
' | sort) > "/tmp/l-$tag.txt"
  $SSH "$HOST" "cd $BASE/code/$d && find . -type f -printf '%P %s
' | sort" > "/tmp/r-$tag.txt"
  out=$(join -a1 -a2 -e MISSING -o 0,1.2,2.2 "/tmp/l-$tag.txt" "/tmp/r-$tag.txt"         | awk -v me=BUILD_INFO.json '$2!=$3 || $1 ~ /[^\/]$/ {} $2!=$3 {print}' | grep -v "^BUILD_INFO.json " | head -20)
  if [ -n "$out" ]; then echo "  [$d] 有出入:"; echo "$out" | sed 's/^/      本地= 线上=  /'; else echo "  [$d] 与 HEAD 一致"; fi
done
if [ "$MODE" = check ]; then
  echo "[check] 只报告，什么都没改。要上线去掉 --check。"
  rm -rf "$STAGE"; exit 0
fi

echo "[deploy] 改前备份整包"
BK="$BASE/backup/pre-$SHA-$(date +%H%M%S)"
$SSH "$HOST" "mkdir -p $BK && cp -a $BASE/code $BK/code && cp -a $BASE/.env $BK/env && echo '  备份 -> $BK'"

push_dir() {  # push_dir <目录> [keep|clean]：本机没有 rsync，用 tar 管道；clean=顺带清掉线上多余文件
  local d="$1" mode="${2:-keep}" tag
  tag=$(printf '%s' "$d" | tr '/' '_')
  echo "  传 $d"
  tar -C "$SRC/$d" -cf - . | $SSH "$HOST" "mkdir -p $BASE/code/$d && tar -xf - -C $BASE/code/$d" || return 1
  [ "$mode" = clean ] || return 0
  $SSH "$HOST" "cd $BASE/code/$d && find . -type f -printf '%P\n'" 2>/dev/null | sort > "/tmp/remote-$tag.txt"
  (cd "$SRC/$d" && find . -type f -printf '%P\n') | sort > "/tmp/local-$tag.txt"
  # 只删"线上有、这版没有"的，且绝不碰版本戳、缓存与备份
  # 删除范围只限 .py（死模块那一类）：字体/样片/图片这类被前端直接引用的东西
  # 一律不删，宁可留着一个多余文件，也不能删出客户看得见的 404。
  comm -23 "/tmp/remote-$tag.txt" "/tmp/local-$tag.txt" \
    | grep -E '[.]py$' | grep -vE '(__init__|[.])pyc$' > "/tmp/kill-$tag.txt" || true
  if [ -s "/tmp/kill-$tag.txt" ]; then
    echo "  清掉 $d 下 $(wc -l < /tmp/kill-$tag.txt) 个多余文件（死模块就在这个清单里）"
    sed 's/.*/&/' /tmp/kill-$tag.txt | tr '\n' '\0' \
      | $SSH "$HOST" "cd $BASE/code/$d && xargs -0 -r rm -f"
  fi
}

# videogen 只按 .py 清（死模块那一类）；server_static 只传不删 ——
# 那底下是被前端直接引用的字体与样片，仓库一旦滞后，删除动作就是在删客户看得见的东西。
push_dir videogen clean || { echo "[deploy] 传 videogen 失败"; exit 1; }
push_dir server_static keep || { echo "[deploy] 传 server_static 失败"; exit 1; }
for d in renderer/src assets samples; do     # 体积大、可能含运行时内容：只前进不删除
  [ -d "$SRC/$d" ] && push_dir "$d" keep
done

printf '{"sha":"%s","branch":"%s","built":"%s","source":"deploy_to_prod.sh","dirty":false}\n' \
  "$SHA" "$BRANCH" "$(date -Iseconds)" > /tmp/BUILD_INFO.json
cat /tmp/BUILD_INFO.json | $SSH "$HOST" "cat > $BASE/code/videogen/BUILD_INFO.json"

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
