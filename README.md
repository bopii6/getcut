# getcut

把一份素材包（文案 + 图片 + 视频）自动做成 1080×1920 竖屏短视频的本地流水线，
配套一个浏览器里跑的成片台和四步工作台。具体能力、模板、部署见
[getcut/README.md](getcut/README.md)。

## 目录

| 目录 | 是什么 |
|------|--------|
| `getcut/` | **主代码**：Python 管线、Remotion 模板、成片台前端、部署与测试 |
| `docs/` | 文档与调研：复刻方案、逆向报告、对比迭代、工作台走查、最佳实践评估、A/B 对比图 |
| `deliverables/` | 产出：成片 mp4、素材包 zip、素材包目录（不进 git） |
| `design-mockups/` | 界面设计稿与改版对比（HTML / PNG） |
| `_tools/`、`tools/` | 一次性脚本与运维脚本（`git_detour_report.sh` 等） |
| `niwo-render-everything/` | 上游参考实现（git submodule，只读） |
| `_scratch/` | 诊断残留、逆向 dump、旧 worktree 副本（不进 git，可随时删） |

## 跑起来

```bash
cd getcut
pip install -r requirements.txt        # Python 3.12+，ffmpeg 需在 PATH 里
python -m getcut.server                # 工作台 http://localhost:8600
```

```bash
python -m getcut build <素材包目录> -o 成片.mp4 --format data
```

密钥放 `getcut/.env`（从 `getcut/.env.example` 复制，`DEEPSEEK_API_KEY` 必填）。
`GETCUT_ACCESS_TOKEN` 留空时只适合本机自用，上线前必须设置。
