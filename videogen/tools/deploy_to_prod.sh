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
#   bash tools/deploy_to_prod.sh --check          # 只报告线上与 HEAD 差哪些文件（不打包、不跑门禁、零改动）
#   bash tools/deploy_to_prod.sh                  # 按改动面跑门禁 + 校验 bundle + 增量同步 + 重启 + 探活
#   bash tools/deploy_to_prod.sh --rebuild        # 改了 .env / 加依赖时（重建容器才读 env-file）
set -uo pipefail

# 生产机地址只在 deploy/hosts.env 里写一份（换机改那一处，四个脚本一起生效）；
# 未设 VIDEOGEN_DEPLOY_HOST 时取那边的默认值，设了则命令行优先。
_HOSTS="$(dirname "$0")/../deploy/hosts.env"
. "$_HOSTS" || { echo "找不到 $_HOSTS —— 地址的唯一真身在 deploy/hosts.env" >&2; exit 1; }
HOST="${VIDEOGEN_DEPLOY_HOST}"
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

# 闸门不过就别上线（这条是整轮评审的意义所在）。
# 跑哪几条闸门按"这次真的动了什么"选：只改成片台时，后端 21 个测试模块与 ruff
# 一行 Python 都碰不到，全跑一遍只是把部署拖长两三分钟。判不准时 gate_scope 一律往
# "多跑"那侧倒（认不出的路径 = 全套），所以这里宁可多跑不可漏跑。
RS=$($SSH "$HOST" "cat $BASE/code/videogen/BUILD_INFO.json 2>/dev/null" \
      | grep -o '"sha":"[^"]*"' | head -1 | cut -d'"' -f4)
RANGE=""
if [ -n "$RS" ] && git merge-base --is-ancestor "$RS" HEAD 2>/dev/null; then
  RANGE="$RS..HEAD"
  echo "[deploy] 线上在跑 $RS"
else
  [ -n "$RS" ] && echo "[deploy] 线上那版 $RS 不在当前分支上（或被改写过）"
  echo "[deploy] 认不出线上是哪一版 → 按最后一条提交算"
fi
if [ -n "$RANGE" ]; then
  CHANGED=$(git diff --name-only "$RANGE")
else
  CHANGED=$(git diff-tree --no-commit-id --name-only -r "$SHA")
fi
if [ -n "$RANGE" ] && [ -z "$CHANGED" ]; then
  GATES=none; WHY='跳过 · 线上已经是这一版，没有要送的文件'
else
  PLAN=$(printf '%s\n' "$CHANGED" | bash tools/gate_scope.sh)
  GATES=$(printf '%s\n' "$PLAN" | head -1)
  WHY=$(printf '%s\n' "$PLAN" | tail -1)
fi
echo "[deploy] 门禁计划：$WHY"
if [ "$MODE" = deploy ] && [ "$GATES" != none ]; then
  if ! bash tools/selfcheck.sh --only="$GATES" >/tmp/selfcheck.log 2>&1; then
    echo "[deploy] 门禁（$GATES）没过，先别上线"; tail -8 /tmp/selfcheck.log; exit 1
  fi
  echo "[deploy] 门禁绿了（$GATES）"
elif [ "$MODE" = deploy ]; then
  echo "[deploy] 没有门禁管得着的东西，跳过门禁（bundle 漂移校验照做）"
fi

STAGE=$(mktemp -d 2>/dev/null || echo /tmp/vg-stage-$$)
rm -rf "$STAGE"; mkdir -p "$STAGE"
# git archive：只导出提交进库的内容（不含工作树里未提交的改动、不含 .git）
git -C .. archive --format=tar "$SHA" | tar -x -C "$STAGE" || { echo "[deploy] 导出 HEAD 失败"; exit 1; }
SRC="$STAGE/videogen"
[ -d "$SRC/videogen" ] || { echo "[deploy] 导出结构不对（找 $SRC/videogen）"; exit 1; }
# 文本文件归一成 LF：Windows 侧导出的 CRLF 会让每一行都"变了"，
# 比对与回滚都会被这种假差异带偏（二进制原样不动）。
find "$SRC" -type f \( -name '*.py' -o -name '*.js' -o -name '*.mjs' -o -name '*.css' -o -name '*.html' -o -name '*.json' -o -name '*.md' -o -name '*.txt' -o -name '*.ts' -o -name '*.tsx' \) -print0 | xargs -0 -r sed -i 's/\r$//'
echo "[deploy] 文本已归一为 LF"

# 成片台浏览器实际加载的是 server_static/poc/bundle.js，不是 renderer/src/*.tsx。
# 先在本机重建并比对，避免源码已经提交但线上仍跑旧 bundle。
# --check 不打这个包：它承诺"什么都不改"，却要付整条链路里最贵那一步（约 1.5 分钟），
# 而且正式部署时还会再判一次 —— 漂移真发生了照样拦。
if [ "$MODE" = deploy ]; then
  if ! bash tools/build_frontend.sh; then
    rm -rf "$STAGE"
    exit 1
  fi
else
  echo "[deploy] --check 不重建 bundle：这一趟不判「源码与产物漂移」，正式部署时判并拦"
fi

# 只处理这次真的改了的目录（判据与上面选闸门用的是同一份清单）。
# videogen 每次都发（代码目录很小且要清死模块），资源目录只有改到时才参与远端扫描，
# 避免每次部署都给几十 MB 音频做 MD5。
if [ -n "${VIDEOGEN_DIRS:-}" ]; then
  DEPLOY_DIRS="$VIDEOGEN_DIRS"
else
  DEPLOY_DIRS="videogen"
  while IFS= read -r path; do
    case "$path" in
      videogen/server_static/*|server_static/*) DEPLOY_DIRS="$DEPLOY_DIRS server_static" ;;
      videogen/renderer/src/*|renderer/src/*)  DEPLOY_DIRS="$DEPLOY_DIRS renderer/src" ;;
      videogen/assets/*|assets/*)              DEPLOY_DIRS="$DEPLOY_DIRS assets" ;;
      videogen/samples/*|samples/*)            DEPLOY_DIRS="$DEPLOY_DIRS samples" ;;
    esac
  done <<< "$CHANGED"
fi

if [ "$MODE" = check ] && [ -z "${VIDEOGEN_DIRS:-}" ]; then
  # --check 是拿来回答"线上到底是不是这一版"的：只扫这次改过的目录，就看不见
  # 别人 scp 上去却没提交的文件 —— 而那正是它该抓的东西。两处代码目录一律扫。
  # 资源目录（assets/samples 几十 MB）不追加：它们只传不删，误报代价远大于扫一遍。
  for d in renderer/src server_static; do
    case " $DEPLOY_DIRS " in *" $d "*) ;; *) DEPLOY_DIRS="$DEPLOY_DIRS $d" ;; esac
  done
fi

# 这些文件不是线上运行时输入：它们会制造无意义的漂移和哈希开销。
list_files() {
  find "$1" -type f \
    ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '*.pyo' \
    ! -name '*.map' ! -name '*.bak*' -printf '%P\n'
}
remote_files() {
  $SSH "$HOST" "cd $BASE/code/$1 && find . -type f \\
    ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '*.pyo' \\
    ! -name '*.map' ! -name '*.bak*' -printf '%P\\n'" 2>/dev/null
}
remote_hashes() {
  $SSH "$HOST" "cd $BASE/code/$1 && find . -type f \\
    ! -path '*/__pycache__/*' ! -name '*.pyc' ! -name '*.pyo' \\
    ! -name '*.map' ! -name '*.bak*' -print0 | xargs -0 -r md5sum" 2>/dev/null
}
local_hashes() {
  (cd "$SRC/$1" && list_files . | while read -r p; do md5sum -t "$p"; done)
}

drift() {  # 线上有、这次要送的版本里没有 → 只报告，不擅自删（缓存类就在这堆里）
  local d="$1" tag only n
  tag=$(printf '%s' "$d" | tr '/' '_')        # renderer/src 这种带斜杠的名字不能直接当文件名
  remote_files "$d" | sort > "/tmp/remote-$tag.txt"
  list_files "$SRC/$d" 2>/dev/null | sort > "/tmp/local-$tag.txt"
  only=$(comm -23 "/tmp/remote-$tag.txt" "/tmp/local-$tag.txt" | head -25)
  n=$(comm -23 "/tmp/remote-$tag.txt" "/tmp/local-$tag.txt" | wc -l)
  if [ "$n" -gt 0 ]; then
    echo "  [$d] 线上独有 $n 个，这次不动它们:"
    echo "$only" | sed 's/^/      /'
  fi
}

if [ "$MODE" = check ]; then
  echo "[deploy] 线上与 HEAD 的差异（与上传时同一套判据：比 md5，不比字节数）"
  for d in $DEPLOY_DIRS; do
    $SSH "$HOST" "test -d $BASE/code/$d" || { echo "  [$d] 线上没有这个目录"; continue; }
    tag=$(printf '%s' "$d" | tr '/' '_')
    local_hashes "$d" \
      | while read -r h x; do printf '%s %s\n' "${x#./}" "$h"; done | sort > "/tmp/l-$tag.txt"
    remote_hashes "$d" \
      | while read -r h x; do printf '%s %s\n' "${x#./}" "$h"; done | sort > "/tmp/r-$tag.txt"
    out=$(join -a1 -a2 -e NONE -o 0,1.2,2.2 "/tmp/l-$tag.txt" "/tmp/r-$tag.txt" \
      | awk '$2 != $3 {print $1 "  本地=" substr($2,1,8) " 线上=" substr($3,1,8)}' \
      | grep -v "^BUILD_INFO.json " | head -20)
    if [ -n "$out" ]; then echo "  [$d] 有出入："; echo "$out" | sed 's/^/      /'; else echo "  [$d] 与 HEAD 一致"; fi
  done
  echo "[check] 只报告，什么都没改。要上线去掉 --check。"
  rm -rf "$STAGE"; exit 0
fi

echo "[deploy] 改前备份整包"
BK="$BASE/backup/pre-$SHA-$(date +%H%M%S)"
$SSH "$HOST" "mkdir -p $BK && cp -a $BASE/code $BK/code && cp -a $BASE/.env $BK/env && echo '  备份 -> $BK'"

push_dir() {  # push_dir <目录> [keep|clean]：本机没有 rsync，用 tar 管道；clean=顺带清掉线上多余文件
  local d="$1" mode="${2:-keep}" tag
  tag=$(printf '%s' "$d" | tr '/' '_')
  # 比内容哈希，不能只比字节数：换色值（#7d7691 → #8c85a3）长度一样，
  # 只比大小会被判成"没变"而漏传，线上会静默留着旧产物（2026-09-21 真踩过）。
  # 远端命令用 printf 经 stdin 交给 sh；路径拼错过一次（漏了 code/）会让清单为空，
  # 所以取不到清单时一律整包发送 —— 宁可多传，不能漏传。
  remote_hashes "$d" \
    | while read -r h p; do printf '%s %s\n' "${p#./}" "$h"; done | sort > "/tmp/rs-$tag.txt"
  # Windows 的 md5sum 默认二进制模式，分隔符是 "*"（路径会被读成 *./auth.py）→ 显式文本模式
  local_hashes "$d" \
    | while read -r h p; do printf '%s %s\n' "${p#./}" "$h"; done | sort > "/tmp/ls-$tag.txt"
  if [ "$mode" = always ]; then
    # 代码目录总共 0.4MB：整包发最省事，也不给"比对说谎"留机会（行尾差异曾让它误判为一致）
    cut -d' ' -f1 "/tmp/ls-$tag.txt" > "/tmp/up-$tag.txt"
  elif [ -s "/tmp/rs-$tag.txt" ]; then
    join -a1 -e MISSING -o 0,1.2,2.2 "/tmp/ls-$tag.txt" "/tmp/rs-$tag.txt" \
      | awk '{if ($2 != $3) print $1}' > "/tmp/up-$tag.txt"
  else
    echo "  [$d] 取不到线上清单，整包发送"
    cut -d' ' -f1 "/tmp/ls-$tag.txt" > "/tmp/up-$tag.txt"
  fi
  n=$(wc -l < "/tmp/up-$tag.txt")
  if [ "$n" -eq 0 ]; then echo "  $d 已经一致，不传"; return 0; fi
  echo "  传 $d（$n 个文件有变化）"
  (cd "$SRC/$d" && tar -cf - --files-from="/tmp/up-$tag.txt")     | $SSH "$HOST" "tar -xf - -C $BASE/code/$d" || return 1
  # 传完回读校验：线上哈希必须与本地一致，否则这次部署算失败（不许"以为传了"）
  remote_hashes "$d" \
    | while read -r h p; do printf '%s %s\n' "${p#./}" "$h"; done | sort > "/tmp/rs2-$tag.txt"
  bad=$(join "/tmp/up-$tag.txt" <(sort "/tmp/ls-$tag.txt") -o 0,1.3,2.2 -2 "/tmp/rs2-$tag.txt" 2>/dev/null \
        | awk '$2 != $3 {print $1}')
  if [ -n "$bad" ]; then
    echo "  [校验失败] 这几个文件传完仍与本地不一致："; echo "$bad" | sed 's/^/      /'
    return 1
  fi
  echo "  $d 已校验一致"
  [ "$mode" = clean ] || [ "$mode" = always ] || return 0
  remote_files "$d" | sort > "/tmp/remote-$tag.txt"
  list_files "$SRC/$d" | sort > "/tmp/local-$tag.txt"
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
# 想只发一部分：VIDEOGEN_DIRS="server_static renderer/src" bash tools/deploy_to_prod.sh
# （线上偶尔会有别的会话 scp 过、还没提交的文件，整包对齐会把它们退回提交版，
#   那种时候先只发自己动过的那几个目录，其余留到确认过再对齐）
for d in $DEPLOY_DIRS; do
  case "$d" in
    videogen) keep=always ;;          # 0.4MB，整包发 + 事后校验，不给误判留空间
    server_static) keep=clean ;;      # 只清 .py（实际没有），产物一律不删
    *) keep=keep ;;
  esac
  push_dir "$d" "$keep" || { echo "[deploy] 传 $d 失败"; exit 1; }
done

printf '{"sha":"%s","branch":"%s","built":"%s","source":"deploy_to_prod.sh","dirty":false}\n' \
  "$SHA" "$BRANCH" "$(date -Iseconds)" > /tmp/BUILD_INFO.json
cat /tmp/BUILD_INFO.json | $SSH "$HOST" "cat > $BASE/code/videogen/BUILD_INFO.json"

if [ "$REBUILD" = 1 ]; then
  echo "[deploy] 重建容器（.env 改动只有重建才生效）"
  $SSH "$HOST" "cd $BASE && bash deploy_new.sh" | tail -6
  rc=${PIPESTATUS[0]}
  if [ "$rc" -ne 0 ]; then
    echo "[deploy] 远端重建失败（退出码 $rc）" >&2
  fi
  rm -rf "$STAGE"
  exit "$rc"
fi

echo "[deploy] 重启并探活"
$SSH "$HOST" "docker restart videogen >/dev/null 2>&1
ok=0
for i in \$(seq 1 25); do sleep 2; curl -fsS --max-time 4 http://127.0.0.1:8600/healthz 2>/dev/null | grep -q '\"ok\":true' && { ok=1; break; }; done
if [ \$ok != 1 ]; then echo '[deploy] 探活失败，回滚'; cp -a $BK/code/. $BASE/code/; cp -a $BK/env $BASE/.env; docker restart videogen >/dev/null 2>&1; sleep 6; docker logs videogen --tail 15; exit 1; fi
echo '[deploy] 服务正常'
curl -s http://127.0.0.1:8600/healthz; echo
docker exec videogen cat /app/videogen/BUILD_INFO.json 2>/dev/null | head -c 160; echo"
rc=$?
rm -rf "$STAGE" /tmp/BUILD_INFO.json
[ $rc -eq 0 ] && echo "[deploy] 完成。回滚：ssh 到服务器执行  cp -a $BK/code/. $BASE/code/ && docker restart videogen"
exit $rc
