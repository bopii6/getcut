# 把出片服务部署到火山引擎服务器

目标机：`115.190.113.128`（火山引擎，Ubuntu/Debian 系概率大，脚本两种包管理器都兼容）

## 先说这台机器的现状

它上面**已经有一整套 Web 端在跑**，别覆盖：

| 已在跑 | 说明 |
|---|---|
| Caddy（:80） | 托管静态网页 + 反代 `/api/*` |
| Web 端页面 | `GetCut · 浏览器出片`，Vite 构建产物 |
| `proxy.mjs` 那套后端 | `/api/plan`、`/api/tts`、`/api/auth`、`/api/gen`、`/api/history`… |
| Node | v18.20.8 |

所以出片服务**不能再用 `/api` 前缀**，会和旧的撞上。方案是挂到 `/v1`：

```
浏览器 ──► Caddy :80 ──┬── /api/*  ──► proxy.mjs（旧，浏览器出片，不动）
                        ├── /v1/*   ──► 127.0.0.1:8902（新，服务端渲染）
                        └── 其余     ──► 静态文件
```

代码里已经做好兼容：`server/api.mjs` 同时接受 `/api`、`/v1` 和无前缀，返回给小程序的 `videoPath` 会带上配置的前缀。

## 部署步骤

### 1. 从本地推文件

```bash
cd /e/getcut
GETCUT_HOST=root@115.190.113.128 bash deploy/push.sh
```

只传运行必需的东西（服务端 6 个文件 + 字体 17MB + .env），不传 remotion 和 665MB 的 broll 素材，大概 20MB。

### 2. 在服务器上安装

```bash
ssh root@115.190.113.128 'cd /opt/getcut-render && bash install.sh'
```

脚本会做六件事：检查 Node ≥18 → 装 ffmpeg → 装 edge-tts → 验中文字体 → `npm i @napi-rs/canvas` → 注册 systemd 服务。**不会碰 Caddy 配置，不会动旧服务。**

装完应该是这样：

```
✓ 服务已起来：http://127.0.0.1:8902/v1/health
{"ok":true,"plan":true,"total":0,"queued":0,"running":0,"concurrency":1}
```

### 3. 加反向代理

在现有 Caddyfile 的站点块里加（位置在静态文件处理之前）：

```caddyfile
handle /v1/* {
    reverse_proxy 127.0.0.1:8902
}
```

```bash
systemctl reload caddy
curl http://115.190.113.128/v1/health
```

到这一步，**用 IP 就能在开发者工具模拟器里出片了**。

### 4. 小程序改一行

`miniprogram/app.js`：

```js
const API_BASE = 'http://115.190.113.128';   // 原来是指向本机的
```

开发者工具「详情 → 本地设置」勾上「不校验合法域名」，然后点生成。

## 真机那道坎：必须有域名 + HTTPS

小程序真机**不接受 IP 地址**，也不接受 http。`wx.request` 的合法域名必须是 HTTPS 的、已备案的域名。所以模拟器能跑通之后，真机还有三件事：

1. 域名 A 记录指向 `115.190.113.128`
2. Caddy 配域名 + 自动申请证书（80/443 要放行）
3. 小程序后台 → 开发管理 → 开发设置 → 服务器域名，把域名加进 `request` 和 `downloadFile`

### 这里有个坑要先确认

火山引擎**中国大陆**的机器，80/443 上跑站点要求域名在该平台完成**接入备案**。你原来的备案如果是在腾讯云做的接入，换到火山属于「变更接入」，需要重新提交，通常 1~3 周。

三条路：

- 走完接入备案（最正，但要等）
- 用火山引擎**香港/海外**节点（免备案，但大陆访问慢，且小程序仍要求域名已备案，这条路其实走不通）
- 暂时只做模拟器验证，等备案下来再上真机

**这条得你或另一个会话去确认，因为它决定了真机什么时候能上。**

## 常用命令

```bash
systemctl status getcut-render      # 看状态
systemctl restart getcut-render     # 重启
journalctl -u getcut-render -n 50   # 看日志
tail -f /var/log/getcut-render.log  # 跟日志
```

## 排错对照

| 现象 | 原因 |
|---|---|
| 出片全屏方框 | 中文字体没注册，`public/fonts` 没传上去 |
| `调不起 ffmpeg` | 没装 ffmpeg，或 PATH 里找不到 |
| `No module named edge_tts` | python3 装了但 edge-tts 没装，或装到了别的 python |
| 接口 404 | Caddy 里 `/v1` 没配，或配在了 file_server 之后 |
| 进度卡在「拆稿」 | DEEPSEEK_API_KEY 没进 .env |
| 首条片特别慢 | ffmpeg 和 canvas 首次加载，正常，第二条就快 |
