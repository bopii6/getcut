# GetCut Next

一句话：**把文案粘进来，本机出片。** AI 拆稿 → 本机配音 → 抓实拍空镜 → Remotion 渲染 → MP4。
没有素材包、没有云端排队、没有账号。

## 打开工作台

```bash
node server.mjs          # http://127.0.0.1:8901
```

页面就三步：粘贴文案 → 选长相 → 生成。右边是手机比例预览，渲完直接播、直接下载。

## 或者用命令行

```bash
node scripts/render.mjs --script demo/餐饮加盟-三个数.txt --theme poster -o out/片子.mp4
node scripts/render.mjs --text "直接写文案" --theme magazine
```

| theme | 长相 |
|---|---|
| `magazine` | 暖纸底 + 印章红，适合律师/咨询/知识 |
| `poster` | 黑金、一屏一句，适合加盟/观点 |
| `dashboard` | 深蓝数字面板，适合教培/测评 |

## 一条片子是怎么出来的

```
文案 ──▶ 拆稿（DeepSeek）──▶ 逐句配音（edge-tts，剪静音）
     ──▶ 抓实拍空镜（Pexels，按句搜竖屏视频）
     ──▶ Remotion 渲染（1080×1920 / 30fps，片头 + 章节页 + 舞台 + 字幕）
     ──▶ MP4
```

- `scripts/plan.mjs`：拆镜头，每句一个卡片类型（hook / stat / list / compare / quote / plain / cta）+ 章节标签 + 英文 b-roll 关键词。
- `scripts/voice.mjs`：逐句配音，剪掉句首尾静音，时长驱动时间轴。
- `scripts/broll.mjs`：Pexels 竖屏实拍，抓不到就退回纯排版。
- `src/Video.tsx` / `src/cards.tsx`：三段式版面（上标题 / 中舞台 / 下字幕），章节转场页、片头。
- `server.mjs` + `web/index.html`：本机工作台页面。

## 依赖（都是本机装好的，跟别的项目无关）

- Node 20+、`node_modules/`（含 Remotion 自带的 headless Chrome，约 300MB，别删）
- ffmpeg 在 PATH 内
- Python 3.12 + `edge-tts`
- 项目根目录 `.env`：`DEEPSEEK_API_KEY`（拆稿）、`PEXELS_API_KEY`（实拍空镜）

双击 `启动.bat`，或 `node server.mjs`，浏览器开 http://127.0.0.1:8901。
断网也能跑，只是会退化成"规则拆稿 + 无实拍"。

## 现在的边界

- 文案 8~1200 字（约 5 分钟），太短拆不出结构。
- 渲染约 3 倍实时：60 秒片子 3~5 分钟（含抓素材）。
- 实拍是"氛围空镜"，不保证和文案严丝合缝；要更准得接图库/品牌素材库。
