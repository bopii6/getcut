#!/usr/bin/env bash
# videogen 更新脚本 v2：配置改用 /opt/videogen/.env（--env-file），改 env 只需编辑该文件后重跑本脚本
set -euo pipefail
cd /opt/videogen

# 首次：从现有容器导出环境变量到 .env
if [ ! -f .env ]; then
  docker inspect videogen --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -E '^(DEEPSEEK_API_KEY|ZHIPU_API_KEY|ALIYUN_ACCESS_KEY|PEXELS_API_KEY|PIXABAY_API_KEY|VIDEOGEN_TOKEN|VIDEOGEN_DEV_EMAIL|VIDEOGEN_WORKSPACE|HOST|PORT|VIDEOGEN_ADMIN_EMAILS|EMAIL_)' > .env
  cat >> .env << 'E2'
# 发信邮箱（注册验证码）：填好后重跑本脚本生效
EMAIL_SMTP_HOST=
EMAIL_SMTP_PORT=465
EMAIL_SMTP_USER=
EMAIL_SMTP_PASS=
EMAIL_FROM=
# 管理员邮箱白名单（逗号分隔）：**必填你自己的邮箱**。
# 权限不再来自"谁先注册"，只来自这一行 —— 万一 /state 的账号文件丢了，
# 没有它你就再也当不上管理员，也就生不成卡密。
VIDEOGEN_ADMIN_EMAILS=
# 开放模式（免登录本机自用）：生产留空。
VIDEOGEN_OPEN_MODE=
# 结构化日志级别（JSON 一行一条进 stdout，docker 按 --log-opt 轮转）。
# 留空 = INFO，够覆盖访问日志；要追一次请求就拿响应头的 x-request-id 过滤：
#   docker logs videogen | jq 'select(.rid=="<rid>")'
VIDEOGEN_LOG_LEVEL=
E2
  echo "[deploy] 已生成 .env"
fi

# 代码备份
BK="backup/code-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BK/videogen" "$BK/server_static"
# 整包备（含 api/ 子目录、ctx.py、BUILD_INFO）：此前是 `*.py` 平铺着拷，server 按域
# 拆进 api/ 之后这份备份会漏掉全部 82 条路由 —— 拿它回滚等于回滚出一个起不来的服务。
cp -a code/videogen/. "$BK/videogen/"
cp -a code/server_static/index.html "$BK/server_static/" 2>/dev/null || true
echo "[deploy] 旧代码已备份 -> $BK"

# 记下"这次上线的到底是哪一版"：生产是宿主绑挂代码、镜像是几天前建的，
# 只有代码目录旁这份 BUILD_INFO.json 能说清在跑的是哪个 commit（容器里读得到，
# 因为 /opt/videogen/code/videogen 就是挂进 /app/videogen 的那一份）。
if git -C code rev-parse --short HEAD >/dev/null 2>&1; then
  SHA="$(git -C code rev-parse --short HEAD)"
  BRANCH="$(git -C code rev-parse --abbrev-ref HEAD)"
  BUILT="$(git -C code log -1 --format=%cI)"
  if [ -n "$(git -C code status --porcelain)" ]; then DIRTY=true; else DIRTY=false; fi
  printf '{"sha":"%s","branch":"%s","built":"%s","dirty":%s,"deployed_at":"%s"}\n' \
    "$SHA" "$BRANCH" "$BUILT" "$DIRTY" "$(date -Is)" > code/videogen/BUILD_INFO.json
  echo "[deploy] 上线版本 $SHA ($BRANCH) 未提交改动=$DIRTY"
else
  echo "[deploy] ⚠️ code/ 不是 git 仓库，写不出 BUILD_INFO —— 以后只能靠镜像标签猜版本"
fi

# 重建容器（先停旧的再改名，避免端口占用）
docker stop videogen >/dev/null
docker rm -f videogen-old >/dev/null 2>&1 || true
docker rename videogen videogen-old
docker run -d --name videogen --restart unless-stopped --network host \
  --log-driver json-file --log-opt max-size=20m --log-opt max-file=5 \
  --env-file .env \
  -v /opt/videogen/data:/data \
  -v /opt/videogen/outputs:/app/outputs \
  -v /opt/videogen/code/server_static:/app/server_static \
  -v /opt/videogen/code/videogen:/app/videogen \
  -v /opt/videogen/code/renderer/src:/app/renderer/src \
  -v /opt/videogen/code/assets:/app/assets \
  -v /opt/videogen/state:/state \
  -v /opt/videogen/backups:/opt/videogen/backups:ro \
  -v /opt/videogen/code/samples:/app/samples \
  -v /opt/videogen/renderer-media:/app/renderer/public/media \
  videogen:latest >/dev/null

# 依赖：这一行以前是 `pip install -q "websockets>=14" "cos-python-sdk-v5>=1.9.3" || true` ——
# 不钉版本（每次部署都可能悄悄换版）、装失败还被吞掉，等于"重建即漂移"每天都在发生。
# 新规则：镜像里已经能 import 的就**不动**（不悄悄升级也不悄悄降级）；缺了才按 requirements.lock
# 装上；装不上就停下，别让服务带着缺依赖起来。线上真实版本看 /api/version。
install_if_missing() {          # $1=import 名  $2=钉死的 pip 规格（要和 requirements.lock 一起改）
  if docker exec videogen python -c "import $1" >/dev/null 2>&1; then
    return 0
  fi
  echo "[deploy] 镜像里缺 $2，按锁定表装上"
  docker exec videogen pip install --no-input -q "$2"
}
install_if_missing websockets "websockets==17.1"
install_if_missing qcloud_cos "cos-python-sdk-v5==1.9.44"

for i in $(seq 1 20); do
  sleep 2
  if curl -fsS --max-time 4 http://127.0.0.1:8600/healthz 2>/dev/null | grep -q '"ok":true'; then
    echo "[deploy] 服务正常（新容器已就绪，旧容器保留为 videogen-old 可回滚）"
    docker exec videogen python -c "from videogen import version; print('[deploy] 容器自报:', version.info())" || true
    exit 0
  fi
done
echo "[deploy] 失败，回滚"
docker rm -f videogen >/dev/null 2>&1 || true
docker rename videogen-old videogen
docker start videogen >/dev/null
docker logs videogen --tail 20
exit 1
