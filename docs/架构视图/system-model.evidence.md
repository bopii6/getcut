# 证据索引 — GetCut 成片台现状模型

模型来源：`system-modeler` + `c4model`（`getcut.structurizr.dsl`）+ `graphviz`（`flow-film-main.dot`、`state-topology.dot`）。
取证日期 2026-09-21，工作区 `E:\短视频生成`，`main` 分支 HEAD `8554f8c`。
路径省略前缀 `videogen/`（即 `videogen/videogen/server.py` 写作 `server.py`）。

置信度定义（插件 `architecture-contract.md`）：**high** = 代码/配置/架构级直证；**medium** = 多个部分信号一致；**low** = 由命名、目录结构或惯例推断；**unknown** = 待核。

---

## 1. 节点证据

| 节点 | 置信度 | 证据 |
|---|---|---|
| 服务端容器（FastAPI + uvicorn 单进程） | high | `server.py:27-28` import、`:54` `app = FastAPI(title="GetCut studio")`、`:2860` `__main__`、`Dockerfile` `CMD python -m videogen.server` + `EXPOSE 8600` |
| 常驻线程池（prep 2 / 灶台 6 / verify 2 / draft 1 / intake 1） | high | `server.py:59`（`_LOCK`）、`:64`、`:74-77`、`:83`、`:2831-2847` 导入期拉起 |
| 鉴权闸门（三通道 + 白名单） | high | `server.py:305-310` 注释、`:312-333` `_PUBLIC_PATHS`、`:336-341` `hmac.compare_digest`、`:675-679` 中间件、`config.py:67` `VIDEOGEN_TOKEN` |
| 无状态 HMAC 会话 | high | `auth.py:334-351`（`email\|exp\|sha256sig`）、密钥 `secrets.token_bytes(32)` + chmod 600；`server.py:311` cookie 名 `vg_session`、`:682-689` HttpOnly/SameSite/Secure；TTL `auth.py:26-27` |
| 账号库 PBKDF2-SHA256 20 万轮 | high | `auth.py:25`、`:133/143` 读写、`:169-189` `create_user`、`:229-230` |
| agenthub（浏览器领单唯一通道） | high | `server.py:2110-2280` 六个 `/api/agent/*`、`:2689-2696` `register/wait_result/is_final_delivered/discard`、`:2722` `on_claim`；救济策略 `agenthub.py:31-34` |
| 生成流水线 | high | `cli.py:118` `build_prep`、`:296` `build_render`、调用点 `:141/153/173/186/196/206/214/257` |
| **画面渲染不在服务器** | high | `cli.py:356-360` `visual_fn is None` 直接 `RuntimeError`；全包 grep 无 node/npx/remotion CLI/chrome 子进程；`remotion_render.py:1-6` 自述；`Dockerfile:2-3,8,11-21`（Node 仅一次性 `toolbundle` 阶段） |
| props.json 生产 | high | `remotion_render.py:232-277`、`cli.py:257/270`、`preview.py:222` |
| 浏览器成片台（渲染+编码+混音） | high | `renderer/src/tool/index.tsx:3,12,562-586`（`renderMediaOnWeb` h264/WebCodecs）、`:591` 交回 |
| 文字几何探针 | high | `renderer/src/NiwoVideo.tsx:1290,1294-1362,1453-1466`（`globalThis.__vgProbe`，双 rAF 等字体稳定） |
| 剪映图层导出 | high | `src/tool/index.tsx:507-547`（`renderStillOnWeb`）、`server.py:2198-2225` 白名单落盘、`agenthub.layer_target:240`、`agenthub.py:37` 文件名白名单 |
| 状态文件族（8 份） | high | 见下表 §3 |
| safestore 三层护栏 | high | `safestore.py:1-12` 自述、`:36-62` 原子写、`:94-115` 变短留底、`:118-141` `_heal`（翻不到抛 `StoreUnrecoverable`） |
| licenses 卡密与档位 | high | `licenses.py:1-13`、`:24` 剔易混字符、`:60-61` 撞码重摇、`:86-93` 只升不降、`:95-100` `auth.set_tier` |
| COS 成片外存 | high | `cos_store.py:1-8` 带宽/盘容动机、`:18-31` 四环境变量、`:43` key 规范、`:48-60` 失败返 False、`:79-91` 签名链；调用点 `server.py:2479-2491/2508/2524-2550/2764-2765` |
| 剪映导入助手 | high | `server_static/assistant/getcut-helper.ps1`、`_tools/build_assistant.py:15-17,45-47,73`、路由 `server.py:1519-1526` |
| 部署：生产走 `deploy_new.sh` 宿主 bind | high | `tools/deploy_new.sh:32-44` 挂载清单、`:46` 在线 pip install、`:55-59` 失败 rename 回滚 |
| 生产 `/state` 里住哪些文件（含 jobs/registry） | high | 2026-09-21 上机核对：`.env` 用 `VIDEOGEN_JOBS_FILE`/`VIDEOGEN_REGISTRY_FILE`/`VIDEOGEN_USERS_FILE`/`VIDEOGEN_LICENSES_FILE`/`VIDEOGEN_AUTH_SECRET`/`VIDEOGEN_BRAND_DIR` 六行指路；`_tools/patch_deploy_state.py:9` 系列补丁完成搬迁。**非本仓代码可推，属线上实况** |
| 8600 只绑 127.0.0.1、对外 Caddy 反代 | high（线上实测） | `server.py:2853-2854` 默认 `HOST=127.0.0.1`；宿主机 `/etc/caddy/Caddyfile` 加 `encode zstd gzip`。注意仓库 `docker-compose.yml:9` 写的是 `8600:8600`，**照它起会裸奔** |
| 每日备份保留 90 天 | high | `tools/backup_state.sh:9` cron 04:30、`:13-34` 打包清单、`:72-91` 保留策略、`:52-70` list/verify/restore |
| GHCR 镜像 CI | high | `.github/workflows/docker.yml:31-41`，context `videogen` |
| `/poc` 产物已入 git | high | `git ls-files server_static/poc` = 24 个 bundle；`.gitignore:47-48` 明确翻案注释（2026-09-21 踩过） |
| 素材包产出端（Agent Skill） | **low** | 仓内无该端代码，只有输入契约 `schemas.py`；由 `复刻方案.md:10-13` 与根目录 6 个 `*-素材包.zip` 侧面支撑 |
| `console/` 管理台 | **low（疑似调试残留）** | `server_static/console/index.html:59,74` 轮询 `/api/job/` + iframe `/poc/?agent=1`，但 `server.py` 对 `console` **零路由**；`git status` 显示 `?? server_static/console/` |
| `_node_setup.sh` 渲染工人节点 | **low（已退役旁支）** | 文件自述 9700 端口只放行主站 IP（`:22-38`），但仓库只剩一个 `docker-compose.yml`，无 `docker-compose.node.yml` |
| `cloud/` | **unknown** | 只有空 `.wrangler/tmp` 残迹，git 零跟踪 → Cloudflare Worker 试验遗留，无owner |
| `niwo-render-everything/` | high（定性为参照物） | `.gitmodules:1-3` + `git ls-files -s` 模式 160000 = git submodule，指向 `MontageAI/niwo-render-everything` |

## 2. 边证据（选关键）

| 边 | 类型 | 置信度 | 证据 |
|---|---|---|---|
| 客户浏览器 → agenthub | async 长轮询 | high | `src/tool/index.tsx:312`（`poll?wait=1&device=`）、`server.py:2119`（长轮询 25s）、`:2094-2101` `_claim_owners` 只领自己的 |
| 成片台 → 服务端 | POST 交回成片 | high | `index.tsx:591`（`?final=1`）、`server.py:2170` |
| 成片台 → 服务端 | POST 交回图层 | high | `index.tsx:507-547`、`server.py:2198-2225` |
| 成片台 → 服务端 | 素材直读 + 预热 | high | `index.tsx:318,344-348`（`force-cache` 校验 200、视频预解码、失败重试一次）、`server.py:2269-2281` |
| 刷新/关页 → 交还任务 | 主动 requeue | high | `index.tsx:206-207` |
| 流水线 → 浏览器（阻塞等件） | in-process 代理 | high | `server.py:2654` `_agent_visual`、`:2725` `_render_job` |
| agent 端点归属校验 | 授权 | high | `server.py:431-458` `_agent_job_ok`（owner 不符 403）、`:2110-2280` 每端点先 `_agent_identity` |
| 任务可见性收口 | 授权 | high | `server.py:1912-1914` 项目/素材包归属、`:1985` `_project_visible`、`:2030` 不存在与无权**同形**返 `unknown` |
| props.json → 成片台 + 草稿（双消费） | 数据契约 | high（存在）/ **low（契约强度）** | 产出 `remotion_render.py:232-277`；消费 `src/tool` 与 `jianying_draft`。**无 JSON Schema、无 pydantic 模型**，见 `schemas.py` 只覆盖 content/manifest |
| 服务端混音兜底分支 | 条件 | high（代码存在）/ **unknown（线上是否还走）** | `cli.py:374-387`：`delivered_final` 为真则跳过 mix/mux，否则服务端 `compose.mix_audio` + `mux` |
| 缺层 → 单轨退化 | 条件 | high | `draft_build.py:154,164-184` 任一张缺失或过小即抛 → `jianying_draft.py:617` 返 None → `:414/718` `build_flat_content` |
| 宿主 bind 遮蔽镜像 baked 前端 | 部署 | high | `deploy_new.sh:36` 挂 `code/server_static` 整目录 ↔ `Dockerfile:68` 镜像内 `COPY --from=toolbundle ... /app/server_static/poc` |

## 3. 状态文件清单

| 文件 | 用途 | 读/写 | 原子写 | 备注 |
|---|---|---|---|---|
| `jobs.json` | 任务表内存快照 | `server.py:1023/1035` | 是 | 只留最近 80 条（`:52`、`:1029-1032`） |
| `registry.json` | 项目登记 projects[]/renders[] | `server.py:1053/1058` | 是 + 变短留底 | 无上限增长，当前 69 项目 |
| `bundles.json` | 素材包归属 | `server.py:362/369` | 是 + 变短留底 | |
| `.videogen-users.json` | 账号表 | `auth.py:133/143` | 是 | 读坏自愈，救不回直接抛（`:134-140`） |
| `.videogen-usage.json` | 免费档日额度 | `server.py:490/501` | 是 | 坏当没记，不挂业务（`:496`） |
| `.videogen-try.json` | 试玩 cookie/IP 限流账本 | `try_topics.guard`（判定与记账同一把锁、键数封顶） | 是 | |
| `.videogen-brand/<sha1(email)[:16]>/` | 客户品牌 + 复刻声 | `brand.py:42/53` | 是 | `brand.json` + `logo.png` + `sample.mp3` |
| `.videogen-licenses.json` | 卡密库 | `licenses.py:39/46` | 是 | **当前文件不存在** |
| `.videogen-auth-secret` | 会话 HMAC 密钥 | `auth.py:334-344` | **否**（`write_bytes` 直写） | 唯一无原子写保护的持久件 |

任务生命周期字段：`stage`、`stage8`、`progress`、`detail`、`error`、`video`、`owner`、`project_id`、`t0/t_stage/t_end`、`cancel`、`render_via`、`cos_key`、`verify`、`try/try_video`（`server.py:1063-1068` 映射表、`:86-87` 活跃阶段）。
`stage` 取值链：`queued → tts → plan → props → prepped → render → audio → mux → verify → done`，终态另有 `failed`、`cancelled`。

## 4. 外部依赖与降级

| 服务 | 用途 | 超时/重试 | 失败处理 | key |
|---|---|---|---|---|
| DeepSeek | 分镜导演、文案改写、章节 | 90s / 2 次（`llm.py:54,254`） | 返回 None → 规则兜底 | `DEEPSEEK_API_KEY`（`config.py:37`，兼容 `deepseek_key.txt`） |
| 智谱 | `glm-4-flash` 备用；`glm-4v-flash` 画面复核 | 60s / 无重试（`llm.py:30,335`） | `None`，只记 warning | `ZHIPU_API_KEY`（`config.py:38`） |
| 百炼 CosyVoice | 主配音（WSS） | open 20s / recv 30-120s / 3 次含「不索取字级时间戳」降级（`tts.py:27,161,324`） | **不静默换渠道，直接抛错**（`tts.py:335`） | `DASHSCOPE_API_KEY`（`config.py:44`） |
| edge-tts | 免费兜底配音 | 3 次 + 3/6s 退避（`tts.py:126,343-354`） | | 无需 key |
| 百炼 voice-enrollment | 声音复刻 | 180s / 3 次（仅 download 错重试） | 抛 `CloneError`（`voice_clone.py:30,68`） | 同上 |
| 腾讯云 COS | 成片外存 | SDK 无显式超时/重试 | 返 False → 保留本地（`cos_store.py:48-60`） | `VIDEOGEN_COS_*`（`:18-24`） |
| SMTP | 验证码 | 20s（`auth.py:120`） | 未配则拒绝注册 | `EMAIL_SMTP_*` |

**读了 key 但包内无调用点**：`ALIYUN_ACCESS_KEY`、`PEXELS_API_KEY`、`PIXABAY_API_KEY`（仅 `config.py:39-41`，素材抓取在仓外 `_tools/*.py`）→ 建模时不画成运行依赖。

## 5. 未知项 / 待核任务

1. ~~`/state` 与 `WORKSPACES` 的真实落位~~ → **已核（2026-09-21 上机）**：`/opt/videogen/state`、`/opt/videogen/data`，靠 `.env` 六行 + bind 生效，代码默认值只在无 env 时用。剩下要核的是**宿主 `code/server_static/poc` 与 git HEAD 是否一致**（不一致就会出现"本机看到的≠线上看到的"）。
2. **免费档出片失败是否退回额度**：额度计数在 `server.py:1923-1932` / `:490-501`，未见失败回退代码。→ 读 `_render_job` 异常分支或做受控实测。
3. **`server_static/console/` 是否要删**：无路由、未入 git。→ 确认是残留还是在用本机调试入口。
4. **`props.json` 契约强度**：两侧各自读写、无 schema。→ 是否值得补 `schemas.py`（本模型只记录事实，不建议方案）。
5. **`compose.mix_audio` 兜底分支线上是否仍会被触达**：代码在，但主路径 `delivered_final` 短路。→ 查一份近期 `jobs.json` 的 `render_via` 分布。
6. **`cloud/`、`.wrangler/`、`_node_setup.sh` 的 owner 与去留**：均无路由或跟踪。
7. **`.videogen-auth-secret` 无原子写**：唯一裸写的持久件。→ 与 `safestore` 的边界是否有意为之。

## 6. 本模型刻意**不**包含的内容

按 `system-modeler` 的场景边界，以下不属于现状建模，已路由给别的技能：
架构风险评级与技术债清单（→ `risk-quality-reviewer`）、运行时网络/发布拓扑细节（→ `deployment-topology-analyzer`，本文只取其挂载事实）、改造建议与迁移计划（→ `evolution-planner`）、图新鲜度与可追溯性校验（→ `architecture-health`）。
