#!/usr/bin/env bash
# 按"这次要上线哪些文件"决定跑哪几条门禁。
#
#   git diff --name-only <线上那版>..HEAD | bash tools/gate_scope.sh
#
# 输出两行：第 1 行 = 要跑的门禁（backend,ruff,frontend,ts 的子集，或 none）
#           第 2 行 = 为什么是这一组（给人看的，部署脚本原样打印）
#
# 为什么要它：全套门禁里最贵的是后端 21 个测试模块 + ruff，而它们只看 Python；
# 成片台改一行 CSS 把它们再跑一遍，等于换根天线也把整车举起来查一遍。
# 判不准时一律往"多跑"那侧倒：认不出的路径 = 全套，宁可多跑不可漏跑。
set -uo pipefail

backend=0; frontend=0; full=0; seen=0
while IFS= read -r p; do
  p="${p%$'\r'}"                        # 从 Windows 侧管道进来会带 \r：不剥掉就全被判成"认不出来"
  [ -n "$p" ] || continue
  seen=1
  p="${p#videogen/}"                     # 仓库根下还有一层同名目录，先剥掉外层前缀
  case "$p" in
    renderer/src/*|server_static/*)
      frontend=1 ;;
    *.py|ruff.toml|requirements*.txt|Dockerfile|docker-compose.yml|tests/*)
      backend=1 ;;
    *.md|*.txt|*.png|*.jpg|*.jpeg|*.gif|*.webp|*.mp4|*.zip|*.otf|*.ttf|*.woff2|\
    design-mockups/*|_diag/*|_qa/*|work/*|docs/*|samples/*|对比/*|选题/*|配音对比/*|音色样例/*)
      : ;;                               # 文档与素材：没有任何门禁覆盖它们
    *)
      full=1 ;;                          # tools/、deploy/、.github/ 以及认不出来的一切
  esac
done

if [ "$seen" = 0 ]; then
  echo 'backend,ruff,frontend,ts'
  echo '全套 · 没拿到文件清单（不知道线上是哪一版，或这一版不在当前分支上）'
  exit 0
fi
if [ "$full" = 1 ]; then
  echo 'backend,ruff,frontend,ts'
  echo '全套 · 清单里有门禁管不着的东西（部署脚本 / CI / 线上配置那一类）'
  exit 0
fi
if [ "$backend" = 1 ] && [ "$frontend" = 1 ]; then
  echo 'backend,ruff,frontend,ts'
  echo '全套 · 后端与成片台都动了'
elif [ "$backend" = 1 ]; then
  echo 'backend,ruff'
  echo '后端 + ruff · 只动了 Python 侧'
elif [ "$frontend" = 1 ]; then
  echo 'frontend,ts'
  echo '前端测试 + 类型检查 · 只动了成片台（renderer/src 与线上产物），后端一行没碰'
else
  echo 'none'
  echo '跳过 · 只送文档与素材，门禁管的东西都不在这份清单里'
fi
