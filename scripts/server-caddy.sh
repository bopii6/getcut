#!/bin/bash
set -e
cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%Y%m%d-%H%M%S)
cat > /etc/caddy/Caddyfile <<'CADDY'
{
	# acme_ca: 强制用 Let-Encrypt 生产 CA，禁止降级到 staging(测试) 环境
	acme_ca https://acme-v02.api.letsencrypt.org/directory
}

# 老产品（Python 服务，仍在 8600）
hellojoy.top, www.hellojoy.top, gc.hellojoy.top {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8600
}

# 新产品：纯静态 + 浏览器出片，/api 走本机 8790
getcut.cn, www.getcut.cn {
	encode zstd gzip
	root * /opt/getcut/web
	handle /api/* {
		reverse_proxy 127.0.0.1:8790
	}
	handle {
		try_files {path} /index.html
		file_server
	}
}
CADDY

caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | tail -3
systemctl reload caddy
sleep 2
echo "--- 本地自测 ---"
curl -sS -o /dev/null -w "首页:%{http_code}\n" --max-time 10 http://127.0.0.1/
curl -sS --max-time 10 http://127.0.0.1/api/health; echo
echo "--- 公网自测 ---"
curl -sS -o /dev/null -w "https:%{http_code} %{time_total}s\n" --max-time 20 https://getcut.cn/
