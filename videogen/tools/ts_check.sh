#!/usr/bin/env bash
# 前端类型检查（renderer/，Remotion + TS）。
#
#   bash tools/ts_check.sh          # 0 错误才算过
#   VIDEOGEN_TS_MAX_ERRORS=3 bash tools/ts_check.sh   # 临时放宽（会被测试拦：不许写进仓库）
#
# 为什么基线是 0 而不是"记录现状"：留一个非零基线，等于把债写进合同 ——
# 以后谁加错都能说"基线里本来就有"。2026-09-21 实测 4 个错，已当场清到 0：
#   · skin.ts resolveSkin 退回的是没补 geo 的基础对象（类型收口，运行时不变）
#   · NiwoVideo.tsx H.size / H.budget 的类型分支里带非数字（断言 + Number()，
#     不补默认值 —— 补默认值等于改字号算法，会改画面）
#   · ZhiguVideo.tsx interpolate 的重载要可变数组（as number[]）
# 改这几处时的共同点：**只做类型层面的收口，一行运行时行为都不动**。
set -uo pipefail
cd "$(dirname "$0")/../renderer"

TSC=node_modules/typescript/bin/tsc
MAX="${VIDEOGEN_TS_MAX_ERRORS:-0}"
if [ ! -f "$TSC" ]; then
  echo "SKIP：renderer/ 里没装 typescript —— 跑 npm i -D typescript@5.9.3 之后再试"
  echo "注意：SKIP 不等于通过。CI 的 node_modules 很小，这一条只在本地跑。"
  exit 0
fi
out="$(node "$TSC" --noEmit -p tsconfig.json 2>&1)"
n="$(printf '%s\n' "$out" | grep -cE 'error TS' || true)"
if [ "${n:-0}" -gt "$MAX" ]; then
  printf '%s\n' "$out" | grep -E "error TS" | head -20
  echo "类型错误 $n 个，上限 $MAX 个：新加的错要么改掉，要么在评审文档里说清为什么留"
  exit 1
fi
echo "tsc --noEmit：$n 个错误（上限 $MAX）"
