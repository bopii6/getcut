"""集中配置：密钥、路径、运行参数。

所有密钥从环境变量读取（支持 .env 文件，见 python-dotenv）。
不再从仓库里的 *_key.txt 明文文件读取。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent      # videogen/
PACKAGE_ROOT = Path(__file__).resolve().parent      # videogen/videogen/

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001 - dotenv 可选，缺失时退化为纯环境变量
    pass


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _legacy_key(env_name: str, legacy_file: str) -> str:
    """优先环境变量；为兼容旧部署，回退到 *_key.txt（若存在）。"""
    val = _env(env_name)
    if val:
        return val
    f = ROOT / legacy_file
    if f.is_file():
        return f.read_text(encoding="utf-8").strip()
    return ""


DEEPSEEK_API_KEY = _legacy_key("DEEPSEEK_API_KEY", "deepseek_key.txt")
ZHIPU_API_KEY = _legacy_key("ZHIPU_API_KEY", "zhipu_key.txt")
ALIYUN_ACCESS_KEY = _legacy_key("ALIYUN_ACCESS_KEY", "aliyun_key.txt")
PEXELS_API_KEY = _legacy_key("PEXELS_API_KEY", "pexels_key.txt")
PIXABAY_API_KEY = _legacy_key("PIXABAY_API_KEY", "pixabay_key.txt")

# 工作台扫描素材包的根目录（默认 videogen 的上级目录）
WORKSPACES = Path(_env("VIDEOGEN_WORKSPACE") or ROOT.parent).resolve()

# 派生目录
WORK = ROOT / "work"
OUTPUTS = ROOT / "outputs"
UPLOADS = ROOT / "uploads"
ASSETS = ROOT / "assets"
STATIC = ROOT / "server_static"
RENDERER = ROOT / "renderer"

# ---------- 渲染模板 ----------
# id 与 renderer/src/skin.ts 的 SKINS 一一对应：一个模板 = 骨架(layout) × 皮肤(配色/字体/装饰/动效)。
TEMPLATES: dict[str, str] = {
    "editorial": "竖屏信息版 · 杂志编辑",
    "finance": "财经数据版",
    "minimal": "极简白版",
    "bleed": "全出血沉浸版",
    "news": "新闻播报版",
    "retro": "复古人文版",
    "portrait": "竖屏满屏",
}
# 旧 format 取值 → 新模板 id（兼容早前发出的请求）
TEMPLATE_ALIAS: dict[str, str] = {
    "portrait_editorial": "editorial",
    "portrait_full": "portrait",
}
DEFAULT_TEMPLATE = "editorial"
