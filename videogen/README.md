# videogen — 本地短视频生成流水线

复刻 niwo.studio「任意内容生成短视频」核心功能的本地实现。输入与 Niwo Agent Skill
完全同构的素材包（content.json + manifest.json + images/ + videos/），输出
1080×1920 竖屏成片。

## 使用

```bash
cd E:\短视频生成\videogen
python -m videogen build <素材包目录> -o 成片.mp4 --format data
```

依赖：Python 3.12+、ffmpeg（PATH 内）、`pip install edge-tts pillow requests`。

## 模板（6 套上架）

一套模板 = **骨架**（editorial/bleed/lower/poster/data/zhigu 六种版式代码）
× **皮肤**（配色/字体/装饰，`renderer/src/skin.ts`）
× **版式几何**（纸卡/面板/媒体窗的尺寸，`renderer/src/layouts.json`，Python 侧读同一份，
剪映草稿的洞与素材位因此不会跟画面漂移）
× **画面语汇**（这套模板能画哪几种卡/舞台动作，`videogen/templates.py`）。

| id | 名字 | 长相 |
|----|------|------|
| `editorial` | 杂志编辑版 | 暖灰纸卡 + 媒体窗 + 信息卡，信息量最足 |
| `news` | 新闻播报版 | 满屏画面 + 底部实色信息条，播报感 |
| `data` | 数据面板版 | 浅色仪表盘：左栏数据、右栏素材 + 进度轨 |
| `poster` | 大字报版 | 黑底荧光黄、一句一屏的超大字 |
| `bleed` | 全出血沉浸版 | 素材铺满全屏，大标题压画面 |
| `zhigu` | 智谷三段式 | 顶带标题 / 中段舞台动作 / 底带字幕 |

加/改模板后**必须重出缩略图与样片**（模板选择器的封面 + 点一下就能看的真片）：

```bash
python tools/make_template_previews.py            # 全部模板：样片 + 缩略图
python tools/make_template_previews.py --no-video # 只补缩略图
```

样片是 6 套模板渲染**同一段演示内容**（`samples/tpl-demo/`，走 clone 复刻路径），
所以样片之间的差别只来自模板本身。

`finance / minimal / retro / portrait` 仍有定义但**未上架**：它们是 editorial/bleed 的
换皮版（版式完全一样），等它们做出自己的版式再放回 `config.TEMPLATES`。

## 节奏（固定 1.1 倍，不给用户调）

- 语速固定 `tts.RATE = "+10%"`（= 1.1 倍）。整条时间轴（分镜、字幕、音效挂点、
  画面总帧数）都派生自 TTS，所以改这一处，全片一起变。
- 镜头长度由规则算，不由大模型决定：`planner.normalize_rhythm()` 按真实时间轴**重新分块**，
  每拍落在 3.8~4.2 秒；大模型只决定"说什么、配什么素材、用哪张卡"。
- 动效速度跟随模板的 `motionFrames`（`useAnimFrame()` 统一折算），改模板节奏不用逐组件改帧数。

## 音效

按"画面什么时候弹出一个东西"逐事件挂，音量统一压在解说之下：

| 分类 | 什么时候响 |
|------|-----------|
| open | 开场 |
| cut | 每次换画面 |
| card | 设计卡/胶囊/榜单弹出 |
| number | 数字落点 |
| emphasis | 金句强调（每一张金句都响） |
| end | 收尾 |

- 库在 `assets/sfx/`（32 个可用）+ `library.json`。**加音效**：mp3 丢进去、清单加一条同类别的。
- 抓新音效：`python tools/fetch_sfx.py`（Mixkit，自动归一化到固定响度）。
- 归一化结果缓存在 `assets/sfx/.norm/`，一条音效只跑一次 loudnorm。
- 试听：工作台里打开 `http://<站点>/sfx-preview`。

## 背景音乐

`assets/music/`（17 首，每条留前 75 秒——反正成片里是循环铺满的）+ `library.json` 的情绪标签。
抓新曲子：`python tools/fetch_bgm.py`。丢文件进目录即出现在选择器，不用改代码。

## 工作台

```bash
python -m videogen.server     # http://localhost:8600
```

四步：导入素材 → 内容确认（模板/音色/音乐/音效）→ 自动生成 → 下载导出。
**点模板 = 播这套模板的样片**，看对眼再定。

## 剪映草稿（分轨）

成片右侧「剪映草稿」导出一个可直接在剪映专业版里二次剪辑的草稿包：

```bash
python -m videogen draft outputs/成片.mp4 -o 草稿.zip   # 也可以在工作台点按钮
```

时间线上每样东西各占一轨，都能单独替换：

| 轨道 | 内容 | 能改什么 |
|------|------|----------|
| 画面 | 按分镜切好的素材片段（1080×1920，位置已摆好） | 右键「替换」换图/换视频 |
| 底板 | 页面底/纸卡/面板（媒体窗留洞）/标题带/页脚，一张图铺满全片 | 一般不用动 |
| 卡片 | 「叠加信息」图形：对比卡/数字卡/事实卡/观点卡/角标/章节标签 | 单独拖动、改时长、删除、换成自己的图 |
| 字幕 | 一句一条文本 | 双击改字、调字号/颜色 |
| 叠加文字 | 卡片上的文字（标题/数字/标签/对比两侧…），逐条独立 | 改字、改颜色、改位置（字体用剪映自带，字号位置为量出的近似值） |
| 配音 | 按句切好的 tts 片段 | 单独重录/替换某一句 |
| 背景音乐 | 循环铺满 + 结尾淡出，音量 20% | 右键替换换歌 |
| 音效 | 每个画面事件一条，每条独立 | 单独替换或删除 |

首次导出要在本机用 ffmpeg 切素材、Remotion 出底板与卡片层并采出文字几何
（约 1-2 分钟，之后有缓存）；没有分轨资产（旧成片 / PIL 渲染）时自动退回
「整条成片按分镜切片」的单轨草稿。

**分层是怎么切的**（改渲染模板时要守住这套约定）：

- **底板层**（一张图片铺满全片）：页面底、纸卡、面板、标题带、页脚。
  底板在素材轨**之上**，所以凡是盖住画面的整块元素都必须**给媒体窗挖洞**
  （editorial 用 `RectWithHole`，data 面板同理）——忘了挖洞素材就整块被盖住。
- **卡片层**（每镜一张）：这一拍才有的东西——设计卡、章节标签、大字、进度轨。
  卡片层里**所有文字都是透明的**（`vg-hide-text`），只有形状；文字由 `TextProbe`
  量出几何后变成剪映的文本轨（可改字）。
- 用 `bottom` / 百分比定位的文字元素，探针会等字体与布局稳定后再量（双 rAF）。
  早了会量到负坐标，剪映里文字直接飘出画面。
- 已知保真度差异：字幕在草稿里是**纯文字轨**，字幕底衬只有大字报（整幅定高带）
  烘进了底板；数据面板那种"跟着文字宽度走的底衬"没有进草稿。

## 部署（腾讯云 / 任意云主机）

```bash
bash deploy.sh          # 自动生成 .env 与访问令牌，拉取或构建镜像，docker compose up
```

- 密钥放 `.env`（从 `.env.example` 复制）；`DEEPSEEK_API_KEY` 必填。
- `VIDEOGEN_TOKEN` 设置后工作台所有数据接口需要令牌（首次打开页面输入一次）；
  留空 = 不鉴权，仅限本机自用。
- 渲染全部在容器内本机完成（Remotion + ffmpeg），没有外部渲染依赖。
- `renderer/src` 与 `videogen/` 都是**挂载进容器**的：改模板/改 Python 只需传文件 +
  `docker restart videogen`，不用重建镜像。

## 流水线（与 Niwo 8 阶段对齐）

| 阶段 | 模块 | 说明 |
|------|------|------|
| 分镜规划 | planner.py | 子句单元切分 → 节奏重分块 → script_anchor 匹配素材 → 首镜片头卡/末镜金句卡 |
| TTS 配音 | tts.py | edge-tts 词级时间戳；多音字用等长同音字替换法修正读音 |
| 画面设计 | llm.py + templates.py | 导演按模板语汇挑卡；模板说明写在 templates.py |
| 画面渲染 | renderer/ (Remotion) | 骨架 × 皮肤 × 几何，props.json 驱动 |
| 音效混音 | compose.py | 逐画面事件挂音效 + BGM 循环淡出，同文件只解码一次 |
| 字幕 | subtitle.py | 子句级 ASS，落在内嵌板字幕区 |
| 画面校验 | verify.py | 逐镜抽帧 + GLM-4V 复核 |

## 开发约定

- 前端测试：`NODE_PATH=tests/.deps/node_modules node tests/frontend.test.cjs`（19 条）。
  改确认页控件要同步改测试与 `tests/frontend-harness.cjs` 的 mock。
- 模板验收脚本：`_tools/_verify/tpl_drives_llm.py`（模板语汇命中率）、
  `_tools/_verify/tpl_vocab.py`（各模板的语汇约束是否生效）。
- 素材授权逐条记在 `assets/sfx/library.json`、`assets/music/library.json`、
  各素材包的 `manifest.json` 里；**不要把音效/音乐当素材转售**。

## 已知与 Niwo 的差距

见 `../对比迭代报告.md`。
