# getcut

把一份素材包（文案 + 图片 + 视频）自动做成 1080×1920 竖屏短视频的本地流水线，
配套一个浏览器里跑的成片台和四步工作台。具体能力、模板、部署见
[getcut/README.md](getcut/README.md)。

## 目录

| 目录 | 是什么 |
|------|--------|
| `getcut/` | **主代码**：Python 管线、Remotion 模板、成片台前端、部署与测试 |
| `docs/` | 全部文档与参考图：复刻方案、逆向报告、对比迭代、走查报告、A/B 对比图、界面设计稿 |
| `workspace/` | 你的素材包与项目数据，服务第一次上传时自动建（不进 git） |

## 跑起来

```bash
cd getcut
pip install -r requirements.txt        # Python 3.12+，ffmpeg 需在 PATH 里
python -m getcut.server                # 打开 http://127.0.0.1:8600
```

打开页面就是成片台：拖素材包 → 生成 → 取片。画面在你这台电脑的浏览器里算，
所以没有"命令行一条命令出 mp4"（`python -m getcut build` 只跑到备料那一步）。

密钥放 `getcut/.env`（从 `getcut/.env.example` 复制，`DEEPSEEK_API_KEY` 必填）。
本机没配 SMTP 时，`.env` 里加 `GETCUT_DEV_EMAIL=1` 就能注册（验证码直接回显在页面上）。
