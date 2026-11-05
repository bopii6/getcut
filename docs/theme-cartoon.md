# 主题：cartoon（卡通主播）

复刻"卡通主播 + 截图 + 大字幕"这个爆款格式，接在现有渲染管线里，和其他主题一样用。

```bash
node scripts/render.mjs --text "文案…" --theme cartoon -o out/xxx.mp4
node scripts/render.mjs --script 文案.txt --theme cartoon
```

拆稿、配音、字幕轴、音乐全部复用原有链路，只有画面层换成这个主题。

## 它长什么样

一屏三层：

1. **上：字幕** —— 小字（章节/第几坑）+ 橙色大字结论；
2. **中：截图** —— 白窗口卡片，带红黄绿三个点、标题栏、几行数据 + 一根柱状图，看起来像真的后台；
3. **下：主播** —— 手绘线稿半身像，被画面下沿切掉，有呼吸和嘴动。

## 五种版面，自动轮换（解决"每屏都一样"）

| 卡类型 | 版面 | 效果 |
|---|---|---|
| `hook` | fullbleed | 大字压上半屏，截图占下半屏 |
| `stat` | split | 左截图 + 右巨大数字 |
| `list` | stage / fullbleed 交替 | 两种构图轮着来 |
| `compare` | duo | 两个人对脸，中间气泡 |
| `quote` / `cta` / `intro` / `chapter` | punch | 全屏一句话，主播缩到角落 |

规则在 `src/cartoon.tsx` 的 `layoutOf()`，改一个 switch 就能调。

## 节奏（解决"节奏慢"）

每个镜头内部再切一刀：`phase` 在镜头 46% 处翻面。

- 截图里的行逐行点亮；
- Duo 的"但是——"后半段才出现；
- 字幕第二行比第一行晚 3 帧入场；
- 切镜前 3 帧 `scale 1.035 → 1`，模拟硬切冲击。

也就是说：**4 秒的一句话，画面有 3 个变化点**，不再是"一张静图挂到底"。

## 换人

主播图在 `public/cartoon/`：

- `host.png` —— 主角（说话有嘴动）
- `host2.png` —— 对场角色（Duo 版面用，自动镜像）

替换成你自己的形象：**先裁掉透明边**（`getbbox()` 之后再存），尺寸 600×600 左右的 PNG 即可，程序按高度 540~560 自适应。

有形象了怎么来：拍一张正脸 + 30 秒录音，用 vidguy / HeyGen 克隆成卡通分身；或者找插画师按你的样子画一张线稿。**这个主题只需要 1~2 张静态图，不需要口型同步。**

## 文案适配

- 每句 ≤ 18 字，拆稿器会把句子拆成 beat，一句一屏；
- 需要数字的句子写在 `title`，`Highlight` 会自动把数字/金额染成橙色；
- `compare` 类型要填 `left` / `right`（左边"你以为"，右边"其实是"）。

## 真截图

不画假 UI 了，直接把后台/产品截图塞进去：

```bash
node scripts/render.mjs --script 文案.txt --theme cartoon --screens demo/screens -o out/x.mp4
```

- `--screens` 目录里放 png / jpg / webp，按文件名排序，逐个贴到正片段落（跳过片头和章节页）；
- 张数不够会循环复用；多了会按顺序分配；
- 截图以 `objectFit: cover` 铺满卡片内容区，`phase` 翻面时轻微推到 1.02；
- 底层字段是 `beat.screenshot`（`src/Video.tsx` 的 Beat 类型里已加），也可以在 props JSON 里手写。

## 批量出片

```bash
node scripts/batch.mjs --topics demo/topics.txt --theme cartoon --screens demo/screens --out out/batch
```

`topics.txt` 一行一条，`|` 后面是文件名：

```
做AI短视频三个月，播放128万，私信零。第一个坑…| 01-避坑
隔壁同行一条691万播放，他只有7000粉…| 02-钩子
```

串行跑，每条独立拆稿 / 配音 / 渲染，失败不中断，最后汇总成功/失败清单。
一条 30~40 秒的片子本机约 **2 分 20 秒**（拆稿 + 配音 + 抓实拍 + 渲染），批量就越跑越顺。

## 已知限制

- 截图是**画出来的假 UI**，不是真截图；要真截图得走 `broll` 字段，或后续加 `screenshot` 卡类型；
- 主播只有嘴动，没有表情切换（要表情需要 3 张图 + 一个状态机，暂未做）；
- 管线仍会抓 Pexels b-roll（`fetchBroll`），但这个主题暂时没用上，等于多花几秒；后续可以把 `--no-broll` 开关接进 render.mjs。
