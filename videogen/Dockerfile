# videogen studio · 云端容器镜像
# Python(FastAPI 管线) + ffmpeg。画面渲染与混音都在客户的浏览器里完成，
# 服务器不装 Node、不装 Headless Chrome——它只做写稿/配音/切音频/封装这些轻活。
#
# 构建： docker build -t videogen .
# 运行： docker run -p 8600:8600 --env-file .env -v videogen-data:/data videogen
FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HOST=0.0.0.0 \
    PORT=8600 \
    VIDEOGEN_WORKSPACE=/data

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

# 2) Python 依赖（先拷贝依赖清单，利用层缓存）
COPY requirements.txt ./
RUN pip install -r requirements.txt

# 3) 应用代码（成片台页面是预先打好的静态包，装在 server_static/poc 里，无需构建）
COPY . .

# 清掉构建期代理，避免运行时误用
ENV HTTP_PROXY= HTTPS_PROXY=

# 4) 运行期可写目录（云上挂卷持久化）
RUN mkdir -p /data /app/work /app/outputs /app/uploads
VOLUME ["/data"]

EXPOSE 8600

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8600/healthz', timeout=4).status==200 else 1)"

CMD ["python", "-m", "videogen.server"]
