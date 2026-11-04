#!/usr/bin/env bash
# git_detour_report.sh —— 从一个仓库的 Git 历史里量化"弯路"
#
# 用法：
#   bash tools/git_detour_report.sh [仓库目录] [> 报告文件.txt]
# 例：
#   bash tools/git_detour_report.sh . > _diag/detour.txt
#
# 十条指标，每条给"怎么判读"。不猜，只数。

set -u
REPO="${1:-.}"
cd "$REPO" 2>/dev/null || { echo "不是仓库目录: $REPO"; exit 1; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "这里没有 git 历史"; exit 1; }

RULE() { printf '\n=== %s\n' "$1"; }
NUM=0

FIRST=$(git log --reverse --format='%ad' --date=short | head -1)
LAST=$(git log -1 --format='%ad' --date=short)
TOTAL=$(git rev-list --count HEAD)

RULE "0. 基本盘"
echo "首个提交 $FIRST，最后 $LAST，共 $TOTAL 个提交"
echo ".git 体积: $(du -sh .git 2>/dev/null | cut -f1)"

RULE "1. 每日提交节奏（哪天在突击）"
git log --format='%ad' --date=short | uniq -c | sort -k2

RULE "2. 返工率：fix / feat 比"
FIX=$(git log --format='%s' | grep -cE '^\s*(fix|修复|hotfix)' || true)
FEAT=$(git log --format='%s' | grep -cE '^\s*(feat|新增|添加)' || true)
echo "feat=$FEAT  fix=$FIX"
if [ "${FEAT:-0}" -gt 0 ]; then
  awk -v f="$FIX" -v t="$FEAT" 'BEGIN{printf "返工率 %.0f%%（>60%% 说明大半力气在还自己上一条提交写下的债；健康线约 30%%）\n", f*100/t}'
fi

RULE "3. 深夜提交（00:00-06:59）——不可逆决策最容易出错的时间窗"
NIGHT=$(git log --date=format:'%H' --format='%ad' | awk '{if ($1+0 < 7) n++} END{print n+0}')
echo "深夜提交 $NIGHT 个"
git log --date=format:'%m-%d %H:%M' --format='%ad' | awk -F'[: ]' '{h=$2+0; if (h<7) print}' | head -12

RULE "4. 同日推翻：一句话里出现退役/下线/拆除/移除/回退/重做/推倒"
git log --date=format:'%m-%d' --format='%ad %h %s' \
  | grep -E '退役|下线|拆除|移除|回退|推倒|重做|不再|整体拆|废弃|清理一次性' || echo "（无）"

RULE "5. 建了又删的死工作量（文件先被加入、后被删除）"
git log --diff-filter=A --name-only --format='' | sed '/^$/d' | sort -u > /tmp/_added.$$
git log --diff-filter=D --name-only --format='' | sed '/^$/d' | sort -u > /tmp/_gone.$$
DEAD=$(comm -12 /tmp/_added.$$ /tmp/_gone.$$ | wc -l)
echo "净消失的文件数: $DEAD（占历史文件总量的比例见下）"
comm -12 /tmp/_added.$$ /tmp/_gone.$$ | head -25
rm -f /tmp/_added.$$ /tmp/_gone.$$

RULE "6. 热点文件（改得最多的前 15）——第一名通常是「什么都往里塞」的那个"
git log --pretty=format: --name-only | sed '/^$/d' | sort | uniq -c | sort -rn | head -15

RULE "7. 闸门晚到：测试/CI 出现在第几个提交"
rank() { # $1=hash -> "第 N / TOTAL"
  local b; b=$(git rev-list --count "$1"..HEAD 2>/dev/null || echo 0)
  echo $(expr $TOTAL - $b)
}
TESTH=$(git log --reverse --diff-filter=A --format='%H' -- 'tests/*' '*/tests/*' '*test_*.py' | head -1)
CIF=$(git log --reverse --format='%H %s' -- '.github/workflows/*' | grep -iE 'ci|gate|门禁|test|verify' | head -1 | cut -d' ' -f1)
if [ -n "${TESTH:-}" ]; then
  git log -1 --date=short --format='测试目录/测试码首次入库: %h %ad %s' "$TESTH"
  R=$(rank "$TESTH"); awk -v r="$R" -v t="$TOTAL" 'BEGIN{printf "  -> 第 %s / %d 个提交（%.0f%%）。前 %.0f%% 的代码没有回归网。\n", r, t, r*100/t, (r-1)*100/t}'
else
  echo "从未提交过测试代码（最危险的一档）"
fi
if [ -n "${CIF:-}" ]; then
  git log -1 --date=short --format='CI 门禁首次入库: %h %ad %s' "$CIF"
  R=$(rank "$CIF"); echo "  -> 第 $R / $TOTAL 个提交"
else
  echo "从未有过 CI 门禁"
fi
echo "测试文件数量变化（只看 tests/ 目录，日志与截图不算）:"
for c in $(git log --reverse --format='%H' | awk 'NR==1 || NR%20==0'); do
  n=$(git ls-tree -r --name-only "$c" -- videogen/tests tests 2>/dev/null | wc -l)
  echo "  $(git log -1 --date=short --format='%ad' $c)  tests=$n"
done

RULE "8. 单体膨胀：热点源码文件 首次入库行数 vs 当前行数"
git log --pretty=format: --name-only | sed '/^$/d' | grep -E '\.(py|ts|tsx|js|cjs|html|css)$' \
  | sort | uniq -c | sort -rn | head -6 | while read c f; do
    addc=$(git log --reverse --diff-filter=A --format=%H -- "$f" | head -1)
    now=$(git show "HEAD:$f" 2>/dev/null | wc -l); first=$(git show "$addc:$f" 2>/dev/null | wc -l)
    echo "$f  改$c次  行数 ${first:-0} -> ${now:-0}"
  done

RULE "9. 二进制/产物反复入库（同一路径提交 >=3 次且当前 >300KB）"
git log --pretty=format: --name-only | sed '/^$/d' | sort | uniq -c | sort -rn > /tmp/_churn.$$
awk '$1>=3' /tmp/_churn.$$ | while read c f; do
  case "$f" in *.png|*.jpg|*.mp4|*.zip|*.woff*|*.otf|*.ttf|*.bundle.js|*bundle*.js|*.mp3) sz=$(wc -c < "$f" 2>/dev/null || echo 0)
      if [ "${sz:-0}" -gt 300000 ]; then printf '%-6s %8s KB  %s\n' "$c 次" "$((sz/1024))" "$f"; fi ;; esac
done | head -12
rm -f /tmp/_churn.$$

RULE "10. 症状补丁链：同一 scope 一天内 >=3 个 fix（同一个坑反复拍）"
git log --date=short --format='%ad %s' \
  | awk '/^[0-9]{4}-/ {d=$1; s=$0; sub(/^[^ ]+ /,"",s); if (s ~ /^(fix|修复)/) { if (match(s,/\([^)]*\)/)) sc=substr(s,RSTART+1,RLENGTH-2); else sc="(无scope)"; cnt[d" "sc]++ }}
         END { for (k in cnt) if (cnt[k]>=3) print cnt[k]"  "k }' | sort -rn

RULE "怎么读这份报告"
cat <<'EOF'
2  返工率：高于 60% 说明"先写后修"取代了"先定再写"，多半是架构或视觉方向没定就开工。
3  深夜提交：00:00-06:00 做的"重做/换方向"类决策，第二天的推翻率最高。
4  同日推翻：这一栏每出现一次，都是一次可以提前半天问清楚的决定。
5  死工作量：建了又删的文件；连续几天大删 = 那条路本不该走。
6  热点文件：改动次数第一且行数上千 = 单体；单体是"测试晚到"和"并行互抹"的共同根因。
7  闸门晚到：测试/CI 出现在 50% 之后，前面所有代码都在靠人肉回归。
9  产物入库：构建产物进历史，仓库会永久变重（clone/部署都变慢），要用 release 或对象存储。
10 症状补丁链：同一天同模块 3 个以上 fix，几乎一定是"信了外部数据源，没自己造真值"。
EOF
