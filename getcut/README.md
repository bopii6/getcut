# getcut — 本地短视频生成流水线

复刻 niwo.studio「任意内容生成短视频」核心功能的本地实现。输入与 Niwo Agent Skill
完全同构的素材包（content.json + manifest.json + images/ + videos/），输出
1080×1920 竖屏成片。

## 使用

```bash
cd E:\getcut\getcut
python -m getcut.server          # 打开 http://127.0.0.1:8600，拖素材包 → 生成 → 取片
```

依赖：Python 3.12+、ffmpeg（PATH 内）、`pip install -r requirements.txt`。

**画面只在浏览器里渲**（成片台，客户自己那台电脑算），所以没有"一条命令直接出 mp4"
的 CLI：`python -m getcut build` 只跑到备料（TTS + 分镜 + 音频），最后一步会明确报
"缺少 visual_fn"。要出片就起服务、在页面里点生成。

## 模板（7 套上架）

一套模板 = **骨架**（editorial/bleed/lower/poster/data/zhigu/macro 七种版式代码）
× **皮肤**（配色/字体/装饰，`renderer/src/skin.ts`）
× **版式几何**（纸卡/面板/媒体窗的尺寸，`renderer/src/layouts.json`，Python 侧读同一份，
剪映草稿的洞与素材位因此不会跟画面漂移）
× **画面语汇**（这套模板能画哪几种卡/舞台动作，`getcut/templates.py`）。

| id | 名字 | 色相族 | 长相 | 独占记号（只有这套有） |
|----|------|--------|------|------------------------|
| `editorial` | 杂志编辑版 | 印章朱红 | 暖灰纸卡 + 媒体窗 + 信息卡，信息量最足 | 颗粒纸纹 + 浅暖底 |
| `news` | 新闻播报版 | 冷正红 | 满屏画面 + 底部实色信息条，播报感 | 底部信息条压标题 |
| `data` | 数据面板版 | 钴蓝 | 浅色仪表盘：左栏数据、右栏素材 + 进度轨 | 方格纸纹理 + 左右双栏 |
| `poster` | 大字报版 | 荧光黄 | 黑底荧光黄、一句一屏的超大字 | 最快节奏（4 帧） |
| `bleed` | 全出血沉浸版 | **无彩色** | 素材铺满全屏，全片只用黑白，纪录片感 | 细黑体 + 暗角 + 直角 |
| `zhigu` | 智谷三段式 | 紫玉（辅描金） | 顶带标题 / 中段舞台动作 / 底带字幕 | 顶底两段全程钉死 |
| `macro` | 宏观棱镜 | 琥珀金 | 暗底金色章节式，按"章"不按"镜" | 章节号 + 八种图形动作 |

### 模板的最佳实践：先立"差异契约"，再谈配色

**为什么要有这一节**：模板是给客人挑的，不是给工程凑数的。客人点开选择器只有半秒判断
"这套是不是我要的"——两套模板如果只有颜色不一样，那就不叫两套，叫一套加一个配色开关。
所以下面这条是硬约束，不是建议。

**契约：一套模板必须在下面 6 个轴里至少 4 个轴上跟其它 6 套都不同。**

| 轴 | 取值举例 | 说明 |
|----|----------|------|
| 骨架 | editorial / bleed / lower / poster / data / zhigu / macro | 元素摆位，最强的差异 |
| 底色明暗 | 浅底 / 暗底 | 缩略图在 270px 宽下**第一眼就是这个**，浅暗不能撞 |
| 强调色色相族 | 朱红 / 正红 / 钴蓝 / 荧光黄 / 无彩色 / 紫玉 / 琥珀金 | **一族只准一套占**，撞了就是没差异 |
| 字重字族 | 特粗黑 / 常规黑 / 细黑 / 等宽数字 | 一律无衬线（客户口径），差异靠字重、字距、等宽 |
| 质感 | 颗粒 / 方格 / 网点 / 暗角 / 无 | 只有 1~2 套该有质感，人人都有等于都没有 |
| 画面语汇与配额 | 能画哪几种卡、一屏几张 | 见 `templates.py` 的 `cards` 与 `_QUOTA` |

配套三条口径：

1. **一套模板一个"独占记号"**，而且这个记号要在缩略图那一帧上看得见。上表的最后一列就是
   各套的记号；做不出独占记号的模板不该上架——`finance / minimal / retro` 就是因为只有换皮、
   没有自己的版式，才留在货架下面（见下）。
2. **色相族不许两套共用**。2026-09-23 之前 7 套里有 4 套共用黄/金（`bleed #f0b429`、
   `poster #ffd400`、`zhigu #ffd93d`、`macro #e8a833`），加上 `news`/`bleed`/`poster` 同属
   "满屏素材压字"一族，7 套实际只给出 4 种观感。现已按上表拆成 7 套 7 族：`bleed` 收成
   **全片零彩色**（银白强调色 + 细黑体 + 暗角 + 直角），`zhigu` 换 **紫玉描金**（与工作台同一张脸），
   `editorial` 的锈红改成 **印章朱红** 与 `news` 的冷正红分开。
3. **质感开关要省着用**：`grain / grid / vignette / LIGHT 细黑体` 这四个已实现的记号，
   目前只有 `grain` 上过屏（editorial），其余三个全住在未上架的皮肤里。宁可不加，
   也不要给每套都抹一遍。

**加一套模板要改的地方**（少一处就会出现"能选但画不出来"或"画面与剪映草稿对不上"）：

1. `renderer/src/layouts.json` — 加这个 id 的版式几何。**没有这一条时 TS 与 Python 会双双
   回落成 editorial 的几何**（`skin.ts buildGeo()` 与 `draft_build.py layout_of()` 都是这个
   回落逻辑），剪映草稿就会照着 editorial 的形状在满屏画面上挖洞。`macro` 就漏过这一条
   （2026-09-23 补上：满屏、不挖洞、不做推镜）。
2. `renderer/src/skin.ts` — 加皮肤，并把 `layout` 填成真实骨架。
3. `getcut/templates.py` — 加 `TEMPLATES_DEF` 一条：`cards`/`modes` 只能填渲染端真画得出来的，
   再写 `director_note` 告诉导演这套的叙事气质；要限信息密度就在 `_QUOTA` 加一行。
4. `getcut/config.py` — 进 `TEMPLATES` 才上架（`cli.py` 与 `preview.py` 都按这张表校验，
   不在表里的 id 会被回落成 `DEFAULT_TEMPLATE`）。
5. `renderer/src/tool/index.tsx` 的 `TPL_HINT` — 一句大白话讲清长相。
6. 跑 `python tools/make_template_previews.py` 重出封面，**并确认挑到的那一帧正好带着这套的
   独占记号**（`thumb_frame()` 优先挑带设计卡的镜头，对 `poster` 这种卖点是"一屏一句超大字"
   的模板会挑错帧——要按模板换挑选策略就改这个函数）。

**这条命令只出封面，不出样片。** 画面渲染 2026-09-20 起只能在客户的浏览器成片台里跑
（`cli.py` 里没有 `visual_fn` 会直接抛错），`sample-<id>.mp4` 那批样片本脚本产不了——
要更新样片，只能在成片台里用 `samples/tpl-demo/` 各跑一遍。脚本结尾会点名"哪些样片比
封面旧"，别让选择器悄悄演旧片。封面这一侧走的是 `renderer/_still.mjs` + `src/still/index.tsx`：
只借 `@remotion/renderer` 出单帧，不碰那条已退役的整片渲染链路。

**为什么卡片语汇要按模板收窄**：模板只限定"能用哪些画面语言"，不规定"第几拍出什么"——
哪句配哪卡仍由大模型判断，但模型只能从这套模板看得懂的语汇里挑，挑了画不出来的会被回落。
`poster` 只留 4 种卡、`editorial` 给满 8 种，就是这个道理。

**验收方式**：7 套封面渲染的是同一段演示内容（`samples/tpl-demo/`），所以封面之间的差别
只来自模板本身。把它们并排看——**认不出谁是谁就是没做到**。

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
python -m getcut.server     # http://localhost:8600
```

四步：导入素材 → 内容确认（模板/音色/音乐/音效）→ 自动生成 → 下载导出。
**点模板 = 播这套模板的样片**，看对眼再定。

## 剪映草稿（分轨）

成片右侧「剪映草稿」导出一个可直接在剪映专业版里二次剪辑的草稿包：

```bash
python -m getcut draft outputs/成片.mp4 -o 草稿.zip   # 也可以在工作台点按钮
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

底板与卡片层这两层图不是服务器画的：成片台在交回成片之后，继续在客户浏览器里
逐镜渲出透明 PNG 交回来（连同量好的文字几何）。服务器只做 ffmpeg 切素材/切配音。
图层没交齐（旧成片 / 客户提前关了页面）时自动退回「整条成片按分镜切片」的单轨草稿。

**分层是怎么切的**（改渲染模板时要守住这套约定）：

- **底板层**（一张图片铺满全片）：页面底、纸卡、面板、标题带、页脚。
  底板在素材轨**之上**，所以凡是盖住画面的整块元素都必须**给媒体窗挖洞**
  （整块矩形用 `RectWithHole` 画四条边带；整层元素用 `ChromeClip` 套 clip-path）
  ——忘了挖洞素材就整块被盖住。
  `ChromeClip` 的 polygon **不许写 `evenodd` 前缀**：成片台那套软件合成器按
  「每点 x y」解析 polygon()，evenodd 会被当成第一个点，整张底板直接渲崩
  （视频走 full 模式不碰这里，所以只有出图层会炸）。改写法见 `holeClip`。
- **卡片层**（每镜一张）：这一拍才有的东西——设计卡、章节标签、大字、进度轨。
  卡片层里**所有文字都是透明的**（`vg-hide-text`），只有形状；文字由 `TextProbe`
  量出几何后变成剪映的文本轨（可改字）。
- 用 `bottom` / 百分比定位的文字元素，探针会等字体与布局稳定后再量（双 rAF）。
  早了会量到负坐标，剪映里文字直接飘出画面。探针找画面根节点只能从自己身上
  `closest('[data-vg-frame]')`，不能 `document.querySelector`（页面里同时存在播放器
  和每张 still 各自的脚手架）；量到的结果走 `probeSink()` 挂到 globalThis——
  webpack 分包会把模块装进多个 chunk，模块级常量会变成两份，页面永远读不到。
- 已知保真度差异：字幕在草稿里是**纯文字轨**，字幕底衬只有大字报（整幅定高带）
  烘进了底板；数据面板那种"跟着文字宽度走的底衬"没有进草稿。

## 部署（腾讯云 / 任意云主机）

```bash
bash deploy.sh          # 自动生成 .env 与访问令牌，拉取或构建镜像，docker compose up
```

- 密钥放 `.env`（从 `.env.example` 复制）；`DEEPSEEK_API_KEY` 必填。
- `GETCUT_ACCESS_TOKEN` 设置后工作台所有数据接口需要令牌（首次打开页面输入一次）；
  留空 = 不鉴权，仅限本机自用。
- 画面渲染与混音都在**客户的浏览器**里完成（成片台，`renderer/src/tool`），容器里
  不装 Node 也不装 Chrome；服务器只做写稿/配音/切音频/封装（ffmpeg + 外部 API）。
  成片台页面是预先打好的静态包，放在 `server_static/poc/`（改完模板要重新打包再拷过去，
  这个目录不进 git）。
- `renderer/src` 与 `getcut/` 都是**挂载进容器**的：改模板/改 Python 只需传文件 +
  `docker restart getcut`，不用重建镜像。

## 谁是管理员（2026-09-21 起改成白名单）

以前是"第一个注册的用户自动当管理员"。这条已经删掉：管理员只认
`GETCUT_ADMIN_EMAILS`（逗号分隔的邮箱，注册时按邮箱决定角色，请求体里传什么都不算）。
为什么要改：旧写法等于把最高权限（生成卡密）挂在"账号文件在不在"上 ——
线上账号表在 `/state` 目录挂载里，只要有一次掉回空目录（漏挂、换机、恢复到空卷），
谁先点注册谁是管理员。现在库里没账号也只是"暂时没人是管理员"，不会开门等人抢。

顺带把"开放模式"（免登录本机自用）改成要显式 `GETCUT_OPEN_MODE=1`：
以前它同样只看"没令牌 + 没账号"，那在生产上会和上面的场景一起把全站素材匿名敞开。

## 上线与回滚（2026-09-21 起一条命令）

成片台源码改动后，先把浏览器实际加载的 bundle 一起更新并提交：

```bash
bash tools/build_frontend.sh       # 只构建并校验，不自动改 tracked 文件
cp renderer/browsertool-dist/bundle.js server_static/poc/bundle.js
git add renderer/src server_static/poc/bundle.js
git commit -m "fix(成片台): ..."
```

正式部署脚本会再次构建校验；源码与 bundle 不一致会直接停止，不会把旧前端静默发布。

跑哪几条门禁按"这次真的送了什么"选（`tools/gate_scope.sh` 决定，起点是线上自己的版本戳 `BUILD_INFO.json`）：
只改成片台 → 只跑前端测试 + 类型检查（约 6 秒，后端 21 个测试模块一行 Python 都碰不到）；
只动 Python → 后端 + ruff；动了 `tools/`、`deploy/`、`.github/` 或认不出线上是哪一版 → 全套；
只送文档与素材 → 跳过门禁。判不准一律往多跑那侧倒。部署默认只扫描这次要送的文件涉及的目录，
并跳过 `__pycache__`、`.pyc`、source map 与 `.bak` 备份文件，避免无关文件拖慢远端 MD5；
`--check` 不重建 bundle（省一分半），但会把"这一趟没判漂移"说出来，正式部署时照样拦。

```bash
cd getcut
bash tools/deploy_to_prod.sh --check     # 只看线上与 HEAD 差哪些文件（按 md5）
bash tools/deploy_to_prod.sh             # 上线：门禁→只送已提交内容→传→回读校验→重启→探活
bash tools/deploy_to_prod.sh --rebuild   # 改了 .env 才需要（docker restart 不读 --env-file）
bash tools/rollback_prod.sh              # 列可回滚点
bash tools/rollback_prod.sh 0deed07      # 一键回到那个提交（回滚前也给当前代码留底）
```
生产 `/opt/videogen/code` 不是 git 仓库（服务器到 GitHub 传不动），所以是**从本机推**。
门禁共 4 条：后端 unittest、ruff、前端 node --test、`tools/ts_check.sh`（tsc 0 错误为基线，
本机没装 typescript 时显示"跳过"而不是绿）。三页法定文本在 `getcut/legal.py`，
留存天数只有 `legal.RETENTION` 一处，改文案与改清理逻辑必须同时改它。

## 客户 IP 与限流（改反向代理拓扑前必读）

发验证码、登录、公开试玩、素材直投四处都按 IP 限流。`_client_ip` 只在**直连来源本身是代理段**
（回环、10.、172.16-31.、192.168.、fe80::）时才认 `X-Forwarded-For`，否则一律用直连地址 ——
XFF 第一段是客户端自己写的，无条件信就等于"换一行 header 换一张新脸"。
生产现状（Caddy 与容器同机）落在可信段里，行为不变。
若哪天把反代挪到**另一台公网机器**上，必须给容器加 `GETCUT_TRUST_PROXY_HEADERS=1`，
不然所有客户会被挤进同一个 IP 桶、一起被限死。

## 出事怎么办：备份与恢复

状态备份脚本 `tools/backup_state.sh` 跑在**宿主机**上（cron 每天 04:30 一次），把账号表 / 卡密表 /
登记表 / 任务表 / 试玩与用量 / 品牌套装目录打包到 `/opt/videogen/backups/`，滚动保留 **90 天**，
包 600、目录 700，**打完当场就 `tar tzf` 校验**（解不开的备份不算备份）。
**大件另走 rsync 镜像**（2026-09-24 起，随同一次 cron 跑）：`outputs/`（成片，付过钱的交付物，
云端没底片）镜像到 `backups/outputs-mirror/`——不带 `--delete`，正本误删后镜像还在；
`data/`（素材包）镜像到 `backups/bundles-mirror/`——带 `--delete`，死包不膨胀。镜像前有余量
守卫（正本一半大 + 至少 1G），磁盘不够宁可跳过，不让备份把盘写爆。
容器只以**只读**方式挂那个目录：应用发现状态文件读坏了会自己回包里取；取不到就抛
`StoreUnrecoverable` 拒绝写入 —— 宁可这一单 500，也不许"把坏文件当空库"（那等于重开注册 + 首注册用户变管理员）。

四条命令（都在宿主机敲，`BASE=/opt/videogen`）：

| 要做什么 | 命令 |
|---|---|
| 看有哪些备份包 | `tools/backup_state.sh list` |
| 校验最新包能解开、里面有哪些文件 | `tools/backup_state.sh verify` |
| 从包里取回一个文件（默认落到 `/tmp/restore-<时间戳>`） | `tools/backup_state.sh restore state/.videogen-users.json` |
| 手工打一个新包 | `tools/backup_state.sh` |

`restore` **只把文件取到 /tmp**，你确认内容无误后再自己放回 `$BASE/...` 并重启容器 —— 刻意不做自动覆盖，
免得把"误判的坏"写成真的坏。生产密钥三件套在 `state/`（本机开发仍落 `data/`），文件名先跑 `verify` 看清单再取。

还欠两件（评估文档第 3 节）：备份与正本**同盘**（防误删不防盘坏，云盘快照未开）、以及没做过"空机起服"级别的恢复演练。盘富余的话下一步是把两个镜像目录异地化（对象存储），那时磁盘余量守卫也可以放宽。

## 流水线（与 Niwo 8 阶段对齐）

| 阶段 | 模块 | 说明 |
|------|------|------|
| 分镜规划 | planner.py | 子句单元切分 → 节奏重分块 → script_anchor 匹配素材 → 首镜片头卡/末镜金句卡 |
| TTS 配音 | tts.py | edge-tts 词级时间戳；多音字用等长同音字替换法修正读音 |
| 画面设计 | llm.py + templates.py | 导演按模板语汇挑卡；模板说明写在 templates.py |
| 画面渲染 | 客户的浏览器成片台（renderer/src/tool + web-renderer） | 骨架 × 皮肤 × 几何，props.json 驱动；服务器不参与 |
| 音效混音 | compose.py | 逐画面事件挂音效 + BGM 循环淡出，同文件只解码一次 |
| 字幕 | renderer/src/NiwoVideo.tsx | 子句级字幕由画面模板自己排（showSubtitles 开关） |
| 画面校验 | verify.py | 逐镜抽帧 + GLM-4V 复核 |

## 开发约定

- 前端出片契约测试（离线 29 条，不起服务器也不开浏览器）：
  `NODE_PATH=tests/.deps/node_modules node --test tests/frontend.test.cjs`。
  改确认页控件要同步改测试与 `tests/frontend-harness.cjs` 的 mock。
  "某控件已下线"这类断言走 `assertAbsent(...)`，别把 DOM 节点交给 `assert.equal(x, null)` ——
  失败时 Node 会 inspect 整棵 LinkeDOM 树，实测一次吃掉 63GB 内存再 OOM 崩进程，真原因被盖住。
- 后端闸门（298 条，全离线：鉴权边界 / 状态文件 / 卡密与档位 / 分镜节奏与素材包解析 / 成片台两端协议字段 / 剪映分轨草稿 / 依赖锁定策略 / 版本链路 / 试玩额度 / 路径边界普查；
  只开发环境要 `pip install httpx`）：`bash tools/run_backend.sh`（每个模块独立进程：这些用例都会改 import 期全局常量，
  同一进程混跑会偶发假红 —— 2026-09-21 查「偶发红」查到的根因就在这）。
  四条门禁一起跑（后端 + ruff + 前端 + 类型检查，只读不装包）：`bash tools/selfcheck.sh`；
  单跑一条或几条用 `--only=frontend` / `--only=frontend,ts`（部署脚本就是靠这个按改动面选闸门，名单写错会当场拒，
  免得"一条都没跑"被当成全绿）；
  想确认这脚本不是在自我安慰就跑 `--fail-demo`，或临时加一条会红的测试看它报不报红。
  改 `/media`、`/api/*` 的鉴权或归属、卡密兑换规则、Plan 落盘字段与节奏分块时先看它红不红。
  ⚠️ 这些测试都靠"临时目录 + 显式改指 `auth.USERS_FILE` 等 import 期常量"隔离，
  新增用例请在 `setUp`/`setUpModule` 里自己钉死路径，别只设环境变量（会被别的模块先 import 掉）。
- 静态检查（只闸真缺陷：未定义名 / 无用导入 / 语法错 / `zip` 静默截断等常见陷阱；排版类不开）：
  `python -m ruff check .`，规则就在本目录 `ruff.toml`，本地与 CI 同一份。
- 上面三套（前端契约 / 后端闸门 / 静态检查）在 push / PR 上由 `.github/workflows/tests.yml` 把关（镜像构建是另一条 docker.yml）。
- 模板验收脚本：`_tools/_verify/tpl_drives_llm.py`（模板语汇命中率）、
  `_tools/_verify/tpl_vocab.py`（各模板的语汇约束是否生效）。
- 依赖是**锁死的**：`requirements.txt`（9 个直接依赖，全 `==`）+ `requirements.lock`（36 条传递依赖）。
  镜像与 CI 都装 `requirements.lock`。升级 = 改版本号 → 在虚拟环境里 `pip install -r requirements.lock`
  → 本地跑绿 104 条后端测试 → 再提交；别把 `==` 改回 `>=`（`tests/test_deps.py` 会红）。
  ⚠️ `cos-python-sdk-v5` 只发 sdist，构建时不能给 pip 加 `--only-binary=:all:`。
- 线上是哪一版：登录以后 `GET /api/version` —— 报 commit、分支、构建/部署时间、**有没有未提交改动**，
  以及运行时**真装着的** fastapi/starlette/websockets/pillow 版本。三个来源按优先级：
  镜像构建参数 `GIT_SHA` → 部署脚本落在 `code/getcut/BUILD_INFO.json` → 就地问 git → 都没有报 `unknown`。
  ⚠️ `tools/deploy_new.sh` 里钉的 `websockets==` / `cos-python-sdk-v5==` 必须与 `requirements.lock` 一致（有测试盯着）。
- 素材授权逐条记在 `assets/sfx/library.json`、`assets/music/library.json`、
  各素材包的 `manifest.json` 里；**不要把音效/音乐当素材转售**。

## 已知与 Niwo 的差距

见 `../对比迭代报告.md`。
