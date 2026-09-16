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

# 访问令牌：设置后所有数据接口（/api、媒体、成片）都要求携带；
# 留空 = 不鉴权（仅建议本机自用）。前端会通过 x-auth-token 头或 ?token= 携带。
AUTH_TOKEN = _env("VIDEOGEN_TOKEN")

# 账号体系（邮箱密码登录）存储位置：默认放工作区（云上是持久卷，重启不丢）
USERS_FILE = _env("VIDEOGEN_USERS_FILE") or str(WORKSPACES / ".videogen-users.json")
AUTH_SECRET_FILE = _env("VIDEOGEN_AUTH_SECRET") or str(WORKSPACES / ".videogen-auth-secret")

# 发信邮箱（注册验证码）。任意支持 SMTP 的邮箱均可（QQ/163/企业邮箱）：
#   EMAIL_SMTP_HOST=smtp.qq.com  EMAIL_SMTP_PORT=465（SSL）
#   EMAIL_SMTP_USER=你的邮箱     EMAIL_SMTP_PASS=授权码（不是登录密码）
# 未配置时的行为见 auth.issue_code：默认拒绝注册；VIDEOGEN_DEV_EMAIL=1 时
# 验证码直接回给前端（仅限本机开发，公网千万别开）。
EMAIL_SMTP_HOST = _env("EMAIL_SMTP_HOST")
EMAIL_SMTP_PORT = _env("EMAIL_SMTP_PORT") or "465"
EMAIL_SMTP_USER = _env("EMAIL_SMTP_USER")
EMAIL_SMTP_PASS = _env("EMAIL_SMTP_PASS")
EMAIL_FROM = _env("EMAIL_FROM") or _env("EMAIL_SMTP_USER")
DEV_EMAIL_FALLBACK = _env("VIDEOGEN_DEV_EMAIL") == "1"

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
