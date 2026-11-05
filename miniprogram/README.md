# GetCut 小程序端

云端出片，小程序只当遥控器：粘文案 → 建任务 → 轮询 → 存相册。

## 为什么不在小程序里直接出片

小程序没有 `VideoEncoder` / `AudioEncoder`（WebCodecs），也吃不下这套包体（字体 17MB、素材 665MB，而主包只有 2MB）。详见 `docs/小程序方案调研.md`。

## 跑起来

1. **起服务端**（在仓库根目录）

   ```bash
   npm run draw      # 把 app/src/lib/draw.ts 打包成 Node 能用的模块
   npm run api       # http://127.0.0.1:8902
   ```

2. **改服务端地址**：`app.js` 顶部的 `API_BASE`

3. **导入开发者工具**：直接打开 `miniprogram/` 这个目录

4. **本机联调**：开发者工具里勾上「详情 → 本地设置 → 不校验合法域名」

## 上线前必须做的三件事

| # | 事项 | 在哪 |
|---|---|---|
| 1 | 把域名加进 **request 合法域名** 和 **downloadFile 合法域名** | 小程序后台 → 开发管理 → 开发设置 → 服务器域名 |
| 2 | 域名必须 HTTPS 且已 ICP 备案 | — |
| 3 | 服务端挂在 nginx 后面，`client_max_body_size` 至少 1MB、`proxy_read_timeout` ≥ 60s | nginx 配置 |

> 注意：需要配的是**服务器域名**，不是业务域名。个人主体也能配服务器域名，业务域名（web-view 用）个人主体开不了——但这套方案不用 web-view。

## 服务端接口

| 方法 | 路径 | 干什么 |
|---|---|---|
| GET | `/api/health` | 探活，顺带报并发和片子目录 |
| POST | `/api/plan` | 只拆稿，秒回，给用户先看分镜 |
| POST | `/api/job` | 建任务，立刻返回 id，不等渲染 |
| GET | `/api/job/:id` | 轮询进度 |
| GET | `/api/jobs` | 最近任务 |
| GET | `/api/video/:id` | 取 MP4，支持 Range |

`POST /api/job` 的入参：

```json
{
  "text": "口播稿，8~1200 字",
  "theme": "poster | magazine | dashboard",
  "title": "片头标题",
  "voice": "zh-CN-YunxiNeural",
  "layoutMode": "auto"
}
```

也可以传 `beats`（前端自己拆好稿）跳过拆稿。

## 已知边界

- 渲染串行（`RENDER_CONCURRENCY` 默认 1），一条 60 秒片约 3~5 分钟。并发调大不会更快，只会让内存吃紧。
- 任务的进度状态存在内存里，服务重启后旧任务查不到状态，但片子文件还在 `data/videos/`。
- 相册权限一旦被拒，要靠 `wx.openSetting` 引导，没法静默重试。
