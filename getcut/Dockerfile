# getcut studio · 云端容器镜像
# Python(FastAPI 管线) + ffmpeg。画面渲染与混音都在客户的浏览器里完成，
# 服务器不装 Node、不装 Headless Chrome——它只做写稿/配音/切音频/封装这些轻活。
#
# 构建： docker build -t getcut .
# 运行： docker run -p 8600:8600 --env-file .env -v videogen-data:/data getcut
#
# 成片台页面（/poc/）在下面的 toolbundle 阶段用 Node 打包，最终镜像里不留 Node。
# 产物目录 server_static/poc/ 现在已经入 git（8554f8c，为的是"推上去就能部署"），
# 但**这一步仍然不能省**：镜像里现打的那份一定跟着当前源码走，仓库里那份可能是旧的
# ——谁改了 .tsx 忘了重打，CI 出的镜像就是新源码 + 旧页面。

# ---------- 0) 成片台打包（构建期一次性用完即弃） ----------
FROM node:22-bookworm-slim AS toolbundle
WORKDIR /r
COPY renderer/package.json renderer/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY renderer/ ./
RUN npm run build:tool \
    && rm -f browsertool-dist/*.map \
    && rm -rf browsertool-dist/public/media

# ---------- 1) 运行镜像 ----------
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8600 \
    GETCUT_WORKSPACE=/data

# 这一版镜像是给谁建的：CI 用 --build-arg GIT_SHA=${{ github.sha }} 传进来，
# /api/version 会原样报出来（生产是宿主绑挂代码，所以那条路还得靠 deploy_new.sh 落 BUILD_INFO.json）。
ARG GIT_SHA=unknown
ARG GIT_BRANCH=
ARG BUILD_DATE=
ENV GETCUT_BUILD_SHA=$GIT_SHA \
    GETCUT_BUILD_BRANCH=$GIT_BRANCH \
    GETCUT_BUILD_DATE=$BUILD_DATE

# 国内主机可换成阿里云 apt 源（默认走官方源）
ARG APT_MIRROR=
RUN if [ -n "$APT_MIRROR" ]; then \
      if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" /etc/apt/sources.list.d/debian.sources; \
      fi; \
      if [ -f /etc/apt/sources.list ]; then \
        sed -i "s|deb.debian.org|$APT_MIRROR|g; s|security.debian.org|$APT_MIRROR|g" /etc/apt/sources.list; \
      fi; \
    fi

# 1) ffmpeg + 中文字体（ffmpeg 负责切片/混音/封装，字体供它画封面等叠字用）
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg \
      fonts-noto-cjk fonts-noto-color-emoji fontconfig \
      ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 构建期网络参数（国内主机可传镜像源 / 代理）
#   docker compose build --build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
#   docker compose build --build-arg HTTPS_PROXY=http://host:port
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG HTTP_PROXY=
ARG HTTPS_PROXY=
ENV PIP_INDEX_URL=$PIP_INDEX_URL \
    HTTP_PROXY=$HTTP_PROXY \
    HTTPS_PROXY=$HTTPS_PROXY

# 2) Python 依赖：装**锁定表**，不是 requirements.txt —— 任何一天重建镜像都装到同一批版本。
#    升级流程见 requirements.txt 顶部注释（先在虚拟环境里跑绿 128 条测试再提交）。
#    ⚠️ cos-python-sdk-v5 只有 sdist，别给 pip 加 --only-binary=:all:。
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.lock

# 3) 应用代码 + 成片台产物（toolbundle 阶段现打，不依赖仓库里有没有静态包）
COPY . .
COPY --from=toolbundle /r/browsertool-dist /app/server_static/poc

# 清掉构建期代理，避免运行时误用
ENV HTTP_PROXY= HTTPS_PROXY=

# 4) 运行期可写目录（云上挂卷持久化）
RUN mkdir -p /data /app/work /app/outputs /app/uploads
VOLUME ["/data"]

EXPOSE 8600

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8600/healthz', timeout=4).status==200 else 1)"

CMD ["python", "-m", "getcut.server"]
