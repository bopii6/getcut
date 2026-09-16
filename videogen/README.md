# videogen — 本地短视频生成流水线

复刻 niwo.studio「任意内容生成短视频」核心功能的本地实现。输入与 Niwo Agent Skill
完全同构的素材包（content.json + manifest.json + images/ + videos/），输出
1080×1920 竖屏信息版成片。

## 使用

```bash
cd E:\短视频生成\videogen
python -m videogen build <素材包目录> -o 成片.mp4 --bgm assets/bgm_upbeat.mp3
```

依赖：Python 3.12+、ffmpeg（PATH 内）、`pip install edge-tts pillow`。

## 工作台

```bash
python -m videogen.server     # http://localhost:8600
```

四块：项目台（成片架 + 项目卡）→ 项目页左栏（成片/文案/素材）右栏（模板/音色/语速/渲染按钮 + 实时任务卡）。

## 部署（腾讯云 / 任意云主机）

```bash
bash deploy.sh          # 自动生成 .env 与访问令牌，拉取或构建镜像，docker compose up
```

- 密钥放 `.env`（从 `.env.example` 复制）；`DEEPSEEK_API_KEY` 必填。
- `VIDEOGEN_TOKEN` 设置后工作台所有数据接口需要令牌（首次打开页面输入一次）；
  留空 = 不鉴权，仅限本机自用。
- 渲染全部在容器内本机完成（Remotion + ffmpeg），没有外部渲染依赖。


## 流水线（与 Niwo 8 阶段对齐）

| 阶段 | 模块 | 说明 |
|------|------|------|
| 分镜规划 | planner.py | 句读切分 → script_anchor 匹配素材 → 首镜片头卡/末镜金句卡 |
| TTS 配音 | tts.py | edge-tts 词级时间戳；多音字用等长同音字替换法修正读音 |
| 画面设计 | overlays.py | 从参考成片量取的版式参数：纸卡/方形内嵌板/标题带/页脚 |
| 字幕 | subtitle.py | 子句级 ASS，落在内嵌板字幕区 |
| 最终合成 | compose.py | 图片 Ken Burns、视频 cover 裁切、BGM 混音、逐段渲染后拼接 |

## 版式几何（1080×1920，实测自 Niwo 成片）

- 纸卡 (91,124)-(983,1556)，暖灰纸纹 + 圆角
- 方形内嵌板 (115,596)-(964,1440)
- 媒体窗口 778×440 @(151,667)
- 标题带：两行 88px，第二行高亮块顶到卡片右缘，黑底白字 + 左红条
- 字幕中心 (540,1322) 70px；页脚两行 27px 灰字

## 已知与 Niwo 的差距

见 `../对比迭代报告.md`。
