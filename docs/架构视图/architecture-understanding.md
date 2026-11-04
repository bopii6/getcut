# GetCut 成片台 — 业务架构理解（现状）

> 由 `system-modeler` + `c4model` + `graphviz` 产出，2026-09-21，工作区 `E:\短视频生成`，HEAD `8554f8c`。
> 读者：要改这个产品的人（含未来的我自己）。范围：**只讲现状**，不讲该不该改。
> 每一句断言的证据位置在同目录 `system-model.evidence.md`；图有三个，见文末读图顺序。

---

## 一句话

**一台 Python 服务器负责"想清楚说什么"，客户自己的浏览器负责"把画面画出来"。**

打个比方：这是**中央厨房 + 借客人的灶**。服务器这边写稿、定分镜、配音、备好料（`props.json` + 素材 + 音轨），然后开一张工单；片子的实际烹炒在客户家的灶上完成——客户浏览器里的成片台逐帧合成画面、混音、编成 h264，再把整条成品端回来。服务器只收件、验货、入冷库（COS）。

所以这台机器**不需要 GPU、不需要 Chrome、不需要 Node**，一条 3Mbps 带宽的 40G 轻量机能撑住出片量——这是整套架构最要紧的一条设计取向，代码里三处独立证据互相对齐：

- `cli.py:356-360`：没有 `visual_fn` 就直接 `RuntimeError`，云端 Remotion CLI 渲染与 Node 成片台**已于 2026-09-20 双双退役**；
- `Dockerfile:2-3,11-21`：Node 只活在一次性 `toolbundle` 构建阶段，运行镜像里没有；
- `remotion_render.py:1-6`：文件自述"画面渲染不在这里"。

## 二、业务角色与他们在卖什么

| 角色 | 干什么 | 产品能力 |
|---|---|---|
| **内容创作者（付费客户）** | 丢素材包 → 挑模板/音色/BGM/音效 → 盯进度 → 取 mp4，或再导剪映草稿 | 主收入能力，基础 ¥399 / 高级 ¥599 买断卡密 |
| **试玩访客（未登录）** | 不注册直接出一条带水印的短片 | 获客漏斗，公开端点靠随机码 + cookie/IP 限流 |
| **站长 / 运维（一个人）** | 部署、生成卡密、跑备份、看任务 | 单点，无团队分工 |

**能力地图**（业务语言，不是模块名）：选题素材 → 出片 → 质检 → 交付 → 二次创作。最后这一环是这产品的差异点：**剪映 8 轨分轨草稿**（画面/底板/卡片/字幕/叠加文字/配音/BGM/音效每样单独可替换），把"AI 出的片子"接回人工精修 workflow，而不是只做一条改不动的死片子。

## 三、领域对象（业务上真正存在的东西）

- **素材包 bundle** — 内容层 `content.json`（口播稿、钩子标题 `[[ ]]` 高亮、来源、多音字）+ 素材层 `manifest.json`（每个文件的画面描述与**配句锚点 `script_anchor`**）。契约在 `schemas.py:35,60,85,99`，**缺字段按默认值，不做强校验**。
- **项目 project** — 一次出片的归属容器，`registry.json` 的 `projects[]`，带 `owner` 与 `renders[]` 历史。
- **任务 job** — 出片这件事本身，有 `stage` 状态机（见下）、`owner`、`cos_key`、`render_via`。
- **成片 film** — 本地 `outputs/*.mp4` 与 COS `films/<job前8>/` 两份，**校验通过后才删本地那份**。
- **账号 account / 档位 tier / 卡密 license / 用量 usage** — `auth.py` + `licenses.py`，卡密兑换**只升不降**，同级或高档兑低档直接拒绝且不消耗。
- **客户品牌 brand** — 水印、口号、片头、联系方式、主色、条款 + **复刻声音的 `voice_id`**，按 `sha1(email)[:16]` 分目录住 `/state`。

## 四、成片任务的生命周期（现状，代码直证）

```
queued → tts → plan → props → prepped → render → audio → mux → verify → done
                                                    └ 终态另有 failed / cancelled
```

映射表 `server.py:1063-1068`，对外另发 `stage8` 的 1–8 进度段（对齐竞品那 8 个阶段，见 `复刻方案.md:43-55`）。

推进者**全是后台线程**：`/api/build` 只做入队（`:1956-1958`），`_prep_job`（`:2423`）跑到 `prepped`，再交给 `_render_job`（`:2725`）写 `done`。真实进度由 `_progress_reporter` 闭包上报（`:2400-2420`）；**没有上报时按渐近曲线自己爬**（`:1960-1981`，`_TICK_TAU=130`）——所以进度条百分比不是真实工作量，是"绝不断档"的体验设计。前端靠轮询 `/api/job/{id}` 看结果。

`render` 这一段是唯一会**跨网络等外部算力**的：任务挂进 `agenthub`，服务器线程阻塞等客户浏览器来领。判定口径分两种且**互不占用额度**（`agenthub.py:28-34`）：**静默** 240 秒算失联（缓存素材期成片台每 5 秒报心跳，所以 4 分钟没声音必然是页面没了），收回后最多重派 2 次；**主动交还**（客户刷新页面）另算，上限 10 次，不烧失联额度。待领取最长等 24 小时。这个 240 秒是 2026-09-21 从 10 分钟收紧的——当时有客户为一个已经关掉的标签页白等满 10 分钟、界面一句话都没有。服务器重启时把上次没跑完的任务批量置 `failed`（`server.py:1043-1050`）。

## 五、边界与权限（现状）

**三条放行通道**（`server.py:305-310`）：会话 cookie、访问令牌、开放模式。闸门 `_auth_gate` 全局生效，白名单在 `:312-333`。

归属校验收口比较到位，几个值得记的细节：
- 任务不可见与不存在**返回同一个形状** `unknown`（`:2030`），不泄露"这个 id 存在但不是你的"。
- 每个 `/api/agent/*` 端点都先认设备身份再查任务 owner（`:431-458`，owner 不符 403），`_claim_owners` 保证**只能领自己的单**（`:2094-2101`）。
- `/media/{name}/{path}` 与 `/poc/{rel}` 都有目录穿越防护（`:1889`、`:2253` `is_relative_to`）。
- 剪映草稿与品牌写入是**高级档 402 墙**（`:1409`、`:532-575`）。

**会话没有服务端撤销列表**：签名串 `email|exp|sha256sig`（`auth.py:347-351`）。推论是双向的——换掉 `.videogen-auth-secret` 即全员下线；反之该密钥泄露即可伪造任意用户。这条在本模型里只作为**边界事实**记录，评级留给 `risk-quality-reviewer`。

## 六、数据与状态：一台机器上的三个地段

生产机上（`tools/deploy_new.sh:32-44`）容器挂着四类 bind：`/opt/videogen/state:/state`、`code/videogen:/app/videogen`、`code/renderer/src:/app/renderer/src`、`code/server_static:/app/server_static`，另加只读备份目录。**8600 只绑 `127.0.0.1`，对外靠宿主机 Caddy 反代**（这属运行拓扑，此处只为定位文件落位而引）。

- **`/state`** — 密钥、客户敏感件**与两份核心业务状态**：账号、卡密、品牌（含复刻声音）、auth-secret，加上 `jobs.json`、`registry.json`（`.env` 里用 `VIDEOGEN_JOBS_FILE`/`VIDEOGEN_REGISTRY_FILE` 指过来）。必须是**目录挂载**——单文件挂载点上 `os.replace` 会 `EBUSY`，等于每次出片收尾都失败。
- **`WORKSPACES`（`/data`）** — 客户数据：素材包、项目工作目录、`.intakes/` 投递口、试玩与用量账本。
- **`/app`** — 只放代码与前端产物，**不放状态**。

`server_static/poc/`（线上真正服务的成片台）2026-09-21 起**已入 git**（`8554f8c`，`.gitignore:47-48` 留了翻案注释）。原因就在上面那条挂载里：宿主 `code/server_static` 整目录盖住镜像同名目录，所以 Dockerfile `toolbundle` 阶段烘进镜像的那份成片台**永远不会生效**——更新路径是「本机重打 bundle → 提交 `server_static/poc/` → 推 main → 主机 `git pull` → `docker restart`」，光换镜像不动 UI。

一处不对称：`jobs.json` 只留最近 80 条，`registry.json` 的 `projects[]/renders[]` 无上限增长（当前 69 项目）。同为持久状态，一个会自我裁剪一个不会。

护栏 `safestore.py` 三层：**原子写**（同目录 tmp + fsync + `os.replace`，Windows `PermissionError` 重试 4 次）、**记录数变短先留底**（`*.pre-<ts>`，最多 10 份）、**坏文件绝不当空库**（改名 `*.bad-<ts>` 留现场，从最近 5 个每日备份包里回捞，翻不到就抛 `StoreUnrecoverable` 拒写）。

宿主机 cron 每日 04:30 打 tar.gz、当场 `tzf` 验、`chmod 600`、保留 90 天、剩不到 3 份才告警（`tools/backup_state.sh`）。

## 七、契约强度（这个系统最脆的地方）

| 契约 | 有无模式定义 | 生产方 → 消费方 |
|---|---|---|
| `content.json` / `manifest.json` | **有**，`schemas.py` | 素材包产出端 → `cli.py:141`、`preview.py` |
| `draft_plan.json` | 有，且带 `version==3` 校验 | `draft_build.py:287-310` → `jianying_draft.py:230` |
| `<片>.draft.json` | 有 | `cli.py:442` → `jianying_draft.load_manifest:217` |
| **`props.json`** | **无** | `remotion_render.py:232-277` → 客户浏览器成片台 **和** 剪映草稿，**两边各读各的** |

`props.json` 是整条链路唯一的隐式契约，而它恰好横跨**两种语言、两个进程、两台机器**。`layouts.json` 反过来是一个正面样本：TS 与 Python 共读同一份版式几何（`src/layouts.json:2` ↔ `draft_build.py:23-25`），README 明写这样"剪映草稿的洞与素材位不会跟画面漂移"。

## 八、代码之外的那道分岔：主路径 vs 兜底

两处"如果浏览器没配合，就走老路"的分支，都属于**代码在场但线上是否触达未知**（详见证据索引 §5）：

1. **混音封装**：`cli.py:374-387` — 浏览器交回的是混好音的完整成片（`delivered_final`）就直接收下；否则服务端 ffmpeg 补做 `mix_audio` + `mux`。
2. **剪映分轨**：任一透明 PNG 缺失或过小（`draft_build.py:164-184`）→ 整条退化成把成片当单素材打包的**单轨草稿**（`jianying_draft.py:414/718`）。

## 九、AI 编码指令覆盖情况

**仓库没有 `AGENTS.md` / `QODER.md` / `CLAUDE.md` / `.qoder` 目录**（`find` 零命中）。领域知识散在两处：

- `videogen/README.md` — 质量很高，且**写的正是回归风险**：`ChromeClip` 的 polygon 不许写 `evenodd` 前缀（软件合成器会把它当第一个点，整张底板渲崩，且只在出图层炸）、探针必须 `closest('[data-vg-frame]')` 不能 `querySelector`、量几何要双 rAF 等字体稳定、结果必须挂 `globalThis`（webpack 分包会让模块级常量变两份）。
- 根目录报告群 — `项目最佳实践评估.md`（51KB）、`工作台走查报告.md`、`对比迭代报告.md`、`逆向调研报告-第二轮.md`、`复刻方案.md`。

缺的是：没有一处把这些散点收敛成"改 X 之前必须跑 Y"的指令入口。已知的验证手段有 `tests/frontend.test.cjs`（19 条）、`_tools/_verify/tpl_*.py`、`tools/agent_acl_check.py`、`tools/safestore_check.py`，但**没有 CI 跑它们**（`.github` 只有 `docker.yml` 一条镜像流水线）。这是事实陈述，不是建议。

## 十、未知项（当作待办，不当作已完成）

1. ~~`/state` 与 `WORKSPACES` 的线上真实落位~~ — 已核（2026-09-21 上机）；剩「宿主 `code/server_static/poc` 与 git HEAD 是否一致」待核，不一致就会出现"本机看到的 ≠ 线上看到的"。
2. 免费档出片失败是否退回额度。
3. `server_static/console/` 是残留还是在用的本机调试入口（`server.py` 对它零路由、且未入 git）。
4. `props.json` 无 schema 这件事的实际影响面。
5. 服务端混音兜底分支线上是否还触达（查近期 `jobs.json` 的 `render_via` 分布即知）。
6. `cloud/`、`.wrangler/`、`_node_setup.sh` 的 owner 与去留。

---

## 读图顺序

1. **`getcut.structurizr.dsl`** — 先用 Qoder 的 Structurizr DSL 预览打开，看 `landscape`（谁在用、边界、外部依赖）→ `containers`（服务器只做四件事，画面在浏览器）→ `components`（服务端进程内部）。低置信与参照物用 tags 区分，虚线外框 = 推断。
2. **`flow-film-main.dot`** — 一条素材包进、一条成片出的全过程，含取消/关页/缺层三条非 happy path。用 Qoder 的 DOT 预览打开（本机未装 graphviz，**未做渲染校验**，仅手工过语法）。
3. **`state-topology.dot`** — 谁写哪份文件、住在哪个地段、护栏在哪一层。红框那个 `.videogen-auth-secret` 是唯一没有原子写保护的持久件。
4. **`system-model.evidence.md`** — 上面所有断言的 `file:line` 索引、置信度、外部依赖降级表、待核清单。

## 口诀

> **服务器动脑，浏览器动手；工单挂 agenthub，收片看 delivered_final；**
> **状态三层护（原子写、变短留底、坏文件不自清），密钥只往 /state 搬；**
> **props 无契约是最脆处，layouts 共一份是最稳处。**
