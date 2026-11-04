workspace "GetCut 成片台" "现状架构模型（system-modeler + c4model）。取证日期 2026-09-21，证据来自 E:/短视频生成 工作区代码与配置；置信度见 tags 与同名 .evidence.md。" "1.0" {

    model {

        # ── 人 ────────────────────────────────────────────────
        creator = person "内容创作者（客户）" "上传素材包、挑模板/音色/BGM、拿竖屏成片与剪映草稿" {
            tags "internalUser"
        }
        trial = person "试玩访客" "未登录，凭 cookie + IP 限流走免费试玩" {
            tags "publicActor"
        }
        operator = person "站长 / 运维" "单点：部署、领卡密、备份 /state、管理任务" {
            tags "internalUser"
        }

        # ── 被测系统 ───────────────────────────────────────────
        getcut = softwareSystem "GetCut 成片台" "输入素材包，输出 1080x1920 竖屏成片 + 可选剪映分轨草稿" {

            studio = container "工作台单页 /studio" "手写单文件 HTML，无构建步骤" "HTML/JS" {
                tags "browserRuntime,secondaryEntry"
            }

            compositor = container "成片台 /poc（跑在客户浏览器里）" "画面渲染、编码、混音、剪映图层导出、文字几何探针全在这里，不在服务器" "React 18 + Remotion 4.0.524 + WebCodecs" {
                tags "browserRuntime,computeHeavy"
            }

            api = container "服务端容器 videogen.server" "uvicorn 单事件循环 + 导入期拉起的常驻后台线程池；镜像内无 Node 无 Chrome" "Python 3.12 + FastAPI" {
                tags "coreService"

                routes = component "路由层" "78 个 handler 全部显式声明，无 StaticFiles 挂载" "FastAPI" {
                    tags "coreService"
                }
                gate = component "鉴权闸门 _auth_gate" "会话 cookie / 访问令牌 / 开放模式三通道 + 前缀白名单" "auth.py" {
                    tags "security"
                }
                agenthub = component "渲染工位 agenthub" "浏览器领单的唯一通道：长轮询、心跳、失联 240s 收回、最多重派 2 次" "agenthub.py" {
                    tags "asyncTask,coreService"
                }
                pools = component "流水线线程池" "prep 2 / 灶台 6 / verify 2 / draft 1 / intake 清扫 1；全局可重入锁串行化写" "server.py:59-88" {
                    tags "asyncTask"
                }
                pipeline = component "生成流水线" "素材包解析 → TTS → 时间轴 → LLM 导演 → props 生产 → 封装 → 校验 → 草稿清单" "cli.py + planner/tts/llm/compose/verify" {
                    tags "coreService"
                }
                stores = component "状态存取 safestore" "原子写 + 变短留底 + 坏文件不自清 + 从每日备份回捞；绝不返回空库" "safestore.py" {
                    tags "persistence,guardrail"
                }
                billing = component "账号与档位" "PBKDF2 账号库、HMAC 无状态会话、卡密只升不降、免费档日出片额度" "auth.py + licenses.py" {
                    tags "security"
                }
            }

            statefiles = container "JSON 状态文件库" "jobs / registry / bundles / users / usage / try / brand / licenses" "JSON on disk" {
                tags "datastore"
            }

            ffmpegx = container "ffmpeg / ffprobe 子进程" "只做四件事：混音、封装、抽帧校验、素材清洗与草稿切片" "Native binary" {
                tags "nativeTool"
            }

            helper = container "剪映导入助手 /assistant" "bat 壳 + base64 的 PowerShell，注册 getcut:// 协议" "PowerShell" {
                tags "clientTool"
            }
        }

        # ── 外部系统 ───────────────────────────────────────────
        deepseek = softwareSystem "DeepSeek" "分镜导演与卡片文案改写；90s 超时、2 次重试、失败返回 None 由规则兜底" {
            tags "external"
        }
        zhipu = softwareSystem "智谱 GLM" "glm-4-flash 备用文案渠道；glm-4v-flash 逐镜画面复核。失败只记 warning" {
            tags "external"
        }
        dashscope = softwareSystem "阿里云百炼" "CosyVoice 主配音（WebSocket）+ voice-enrollment 声音复刻。不静默换渠道，失败直接抛错" {
            tags "external"
        }
        edgetts = softwareSystem "Microsoft Edge TTS" "免费兜底配音渠道，3 次退避重试" {
            tags "external"
        }
        tencentCos = softwareSystem "腾讯云 COS" "成片外存（出片带宽仅 3Mbps、系统盘 40G）。四把环境变量缺一即整体退回本地文件" {
            tags "external"
        }
        smtp = softwareSystem "SMTP 邮件服务" "注册与重置验证码；未配置则直接拒绝注册" {
            tags "external"
        }
        jianying = softwareSystem "剪映专业版（客户机）" "消费分轨草稿包，做人工二次剪辑" {
            tags "external"
        }
        niwo = softwareSystem "Niwo 云端工作台" "逆向参照物（git submodule niwo-render-everything），不参与本产品运行链路" {
            tags "reference"
        }
        getcutskill = softwareSystem "素材包产出端（Agent Skill）" "content.json + manifest.json + images/ + videos/ 打成的 zip，即本产品输入契约的生产方" {
            tags "inferred"
        }

        # ── 关系：人 ───────────────────────────────────────────
        creator   -> studio     "登录，导入素材包，挑模板/音色/音乐"
        creator   -> compositor "在浏览器里盯进度条跑完，取回成片"
        creator   -> helper     "装一次，让剪映能接 getcut:// 拉起"
        creator   -> jianying   "打开草稿包做二次剪辑"
        trial     -> getcut     "走公开试玩 /api/try，额度记在 cookie/IP 账本"
        operator  -> api        "跑 deploy_new.sh 滚动更新、生成卡密、查备份"

        # ── 关系：浏览器 ↔ 服务端 ──────────────────────────────
        studio     -> routes    "上传素材包、建项目、提交出片、轮询进度" "HTTP JSON" {
            tags "httpJson"
        }
        compositor -> agenthub  "领单 / 心跳 / 交回成片与图层" "HTTP 长轮询 + POST" {
            tags "asyncTask"
        }
        compositor -> ffmpegx   "取预解码友好的清洗版素材与字体" "HTTP /agent-media" {
            tags "httpJson"
        }
        routes     -> compositor "服务静态 bundle；把 props.json 与素材清单交给它" "HTTP" {
            tags "httpJson"
        }

        # ── 关系：服务端内部 ───────────────────────────────────
        gate     -> routes      "非白名单请求先过闸门"
        routes   -> pools       "只入队，不在请求内做重活"
        pools    -> pipeline    "prep 池与灶台池分段执行流水线"
        pipeline -> ffmpegx     "subprocess 调用"
        pipeline -> agenthub    "挂任务并阻塞等待浏览器交回成片"
        pipeline -> statefiles  "读写任务与项目登记状态"
        stores   -> statefiles  "原子写 / 留底 / 回捞"
        billing  -> statefiles  "账号、档位、用量、品牌、卡密"
        routes   -> billing     "鉴权与额度判定"

        # ── 关系：外部 ─────────────────────────────────────────
        pipeline -> deepseek   "调用" "HTTPS" { tags "externalCall" }
        pipeline -> zhipu      "调用" "HTTPS" { tags "externalCall" }
        pipeline -> dashscope  "调用" "WSS" { tags "externalCall" }
        pipeline -> edgetts    "调用" "WSS" { tags "externalCall" }
        api      -> tencentCos "成片归档上传 / 按需回捞 / 签发下载链接" "HTTPS" { tags "externalCall" }
        billing  -> smtp       "发验证码" "SMTP" { tags "externalCall" }
        helper   -> jianying   "注册协议并投递草稿包" { tags "clientTool" }

        getcutskill -> routes "产出 zip 后由客户上传；契约由本产品 schemas.py 定义，但无强校验" {
            tags "inferred"
            description "低置信：仓内没有该产出端的代码，只有输入契约 schemas.py"
        }
        getcut -> niwo "输入协议与 8 阶段流水线逐项对齐复刻；无运行时调用" {
            tags "reference"
        }
    }

    views {

        systemLandscape "landscape" "业务全景" "谁在用、系统边界、外部依赖" {
            scope *
            include *
            autolayout tb
        }

        container getcut "containers" "容器图" "服务器只做写稿/配音/切音频/封装，画面与混音在客户浏览器" {
            include *
            autolayout tb
        }

        component api "components" "组件图" "服务端进程内部；父容器边界由 Dockerfile CMD 与 server.py 证实" {
            include *
            autolayout tb
        }

        styles {
            element "Person" {
                shape ellipse
                background #EDE7D9
                color #2B2118
                stroke #8C7B62
            }
            element "Software System" {
                background #4A3B6B
                color #F5F2EA
                stroke #2B2140
            }
            # external / reference / inferred 必须排在 "Software System" 之后：
            # Structurizr 样式后匹配者覆盖先匹配者，否则外部系统会被染成主系统的紫。
            element "external" {
                shape hexagon
                background #F0E3D2
                color #5A4632
                stroke #B08A5E
            }
            element "coreService" {
                background #5A6E8C
                color #F5F8FB
            }
            element "browserRuntime" {
                shape roundedBox
                background #8FB5A5
                color #1F3329
                stroke #4E7A66
            }
            element "datastore" {
                shape cylinder
                background #D8C79A
                color #3A3020
            }
            element "nativeTool" {
                shape cylinder
                background #C9BBD6
                color #322840
            }
            element "security" {
                background #B4574A
                color #FDF3F1
            }
            element "guardrail" {
                border #4E7A66
                strokeWidth 3
            }
            element "inferred" {
                border #9A9A9A
                fontSize 11
                opacity 70
            }
            element "reference" {
                border #BBBBBB
                background #EFEFEF
                color #666666
                opacity 60
            }
            relationship "externalCall" {
                color #B08A5E
                dashed true
                thickness 1
            }
            relationship "asyncTask" {
                color #4E7A66
                thickness 3
            }
            relationship "httpJson" {
                color #5A6E8C
                thickness 2
            }
            relationship "inferred" {
                color #9A9A9A
                style dotted
            }
            relationship "reference" {
                color #BBBBBB
                style dashed
            }
        }

        theme default
    }
}
