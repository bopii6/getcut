#!/usr/bin/env bash
# 一条命令复验全部门禁：改完代码想知道"有没有顺手弄坏别的东西"，跑这个。
#
#   bash tools/selfcheck.sh            # 全部
#   bash tools/selfcheck.sh --only=frontend
#   bash tools/selfcheck.sh --fail-demo  # 故意让它红一次，确认这脚本不是在自我安慰
#
# 只读脚本：不装包、不连服务器、不写任何状态文件。
# 三件事一起看才算绿：后端 unittest、ruff 静态检查、前端 node --test。
# CI（.github/workflows/tests.yml）跑的是同样这三条，本地先过一遍省一次来回。
set -uo pipefail
cd "$(dirname "$0")/.."

PY="${PYTHON:-python}"
NODE="${NODE:-node}"
ONLY=""
FAIL_DEMO=0
for arg in "$@"; do
  case "$arg" in
    --only=*) ONLY="${arg#--only=}" ;;
    --fail-demo) FAIL_DEMO=1 ;;
    *) echo "不认识的参数：$arg（可用 --only=backend|ruff|frontend，--fail-demo）" >&2; exit 2 ;;
  esac
done

want() { [ -z "$ONLY" ] || [ "$ONLY" = "$1" ]; }

PASS=0; FAIL=0; SKIP=0; ROWS=""

# 判定不靠退出码单独看：解析器要求"确实跑过 N 条"，
# 否则 import 失败、0 条测试也能被当成绿。
run() {  # run <标签> <命令...>
  local label="$1"; shift
  local out rc
  out="$("$@" 2>&1)"; rc=$?
  local line
  line=$(printf '%s\n' "$out" | grep -E "^(Ran [0-9]+ tests|ℹ tests [0-9]+|All checks passed!)" | head -1)
  if [ "$rc" -eq 0 ] && [ -n "$line" ]; then
    PASS=$((PASS+1)); ROWS="$ROWS
  绿  $label  ·  $line"
  else
    FAIL=$((FAIL+1)); ROWS="$ROWS
  红  $label  ·  退出码 $rc${line:+ · $line}
      $(printf '%s\n' "$out" | tail -3 | tr '\n' '/' | cut -c1-300)"
  fi
}

if [ "$FAIL_DEMO" -eq 1 ]; then
  echo "[selfcheck] --fail-demo：故意跑一个不存在的测试模块，脚本必须报红"
  run "后端（故意坏）" "$PY" -m unittest tests.test_这个模块不存在
  if [ "$FAIL" -eq 0 ]; then
    echo "这个自检查脚本不会红 —— 它等于没在把关"; exit 1
  fi
  echo "好：它确实会红。"; exit 0
fi

want backend  && run "后端 unittest" "$PY" -m unittest discover -s tests -t tests
want ruff     && run "ruff 静态检查" "$PY" -m ruff check .
want frontend && run "前端 node --test" env \
  NODE_PATH=tests/.deps/node_modules "$NODE" --test tests/frontend.test.cjs

# 类型检查单独处理：本机没装 typescript 时是「跳过」—— 既不算绿也不算红，
# 但必须打出来，不然"三条门禁全绿"会悄悄变成"其实没查"。
if want ts; then
  tsout="$(bash tools/ts_check.sh 2>&1)"; tsrr=$?
  if [ "$tsrr" -ne 0 ]; then
    FAIL=$((FAIL+1)); ROWS="$ROWS
  红  前端类型检查  ·  $(printf '%s' "$tsout" | grep -E 'error TS' | head -1)"
  elif printf '%s' "$tsout" | grep -q "SKIP"; then
    SKIP=$((SKIP+1)); ROWS="$ROWS
  跳过 前端类型检查  ·  本机没装 typescript：cd renderer && npm i -D typescript"
  else
    PASS=$((PASS+1)); ROWS="$ROWS
  绿  前端类型检查  ·  $(printf '%s' "$tsout" | tail -1)"
  fi
fi

echo "门禁结果：$PASS 绿 / $FAIL 红${SKIP:+ / $SKIP 跳过}$ROWS"
[ "$FAIL" -eq 0 ] || {
  echo "有红的就别往下走：先修到全绿再提交/部署。"; exit 1; }
echo "全绿。想核线上是哪一版：GET /api/version（要登录），服务器上 docker exec videogen cat /app/BUILD_INFO.json"
