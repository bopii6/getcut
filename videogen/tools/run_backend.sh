#!/usr/bin/env bash
# 后端闸门：每个测试模块单独一个进程跑。
#
# 为什么不是一条 discover 全跑（这是今晚查"偶发红"查出来的根因）：
# 这些模块都会改 import 期的全局常量 —— auth.USERS_FILE / SECRET_FILE / SESSIONS_FILE、
# server.WORKSPACES / OUTPUTS / BUNDLES_META、licenses 的两个文件……
# 同一进程里混跑时"谁先被 import 谁定调"，后跑的模块即使 setUp 里钉过，
# 也可能被别的模块的 tearDown 改回去 → 结果就是偶发假红/假绿。
# 分开跑多花 20 秒，换"判据可信"。
set -uo pipefail
cd "$(dirname "$0")/.."

fail=0; total=0; bad=""
for f in tests/test_*.py; do
  m="tests.$(basename "$f" .py)"
  out="$(PYTHONIOENCODING=utf-8 python -m unittest "$m" 2>&1)"; rc=$?
  ran="$(printf '%s\n' "$out" | grep -oE '^Ran [0-9]+' | head -1 | awk '{print $2}')"
  total=$((total + ${ran:-0}))
  if [ "$rc" -ne 0 ]; then
    fail=1; bad="$bad $m"
    printf '  红  %s\n' "$m"
    printf '%s\n' "$out" | grep -E '^(FAIL|ERROR): ' | head -5
  else
    printf '  绿  %-38s %s 条\n' "$m" "${ran:-0}"
  fi
done
echo "后端合计 $total 条"
if [ "$fail" -ne 0 ]; then echo "有红的模块:$bad"; exit 1; fi
echo "后端全绿"
