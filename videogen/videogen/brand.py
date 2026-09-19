"""品牌套件（高级档）：每用户的 Logo / Slogan / 联系方式 / 品牌色。

存工作区 .videogen-brand/<email哈希>/（logo.png + brand.json），重启不丢。
品牌色从 Logo 里自动抠（Pillow 量化取主色，优先饱和度高的），也可手填；
拼进成片走 cli.build 现成的 theme 直通，不用动模板配色系统。
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import time
from pathlib import Path

from . import config

DIR = Path(config.WORKSPACES) / ".videogen-brand"
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_LOGO = 2 * 1024 * 1024
MAX_SLOGAN = 20
MAX_CONTACT = 30
MAX_OPENING = 40
MAX_TERMS = 20          # 发音库上限：词条数
PINYIN_RE = re.compile(r"^[a-z0-9 ]+$")


def _key(email: str) -> str:
    return hashlib.sha1((email or "").strip().lower().encode("utf-8")).hexdigest()[:16]


def _dir(email: str) -> Path:
    return DIR / _key(email)


def _json_path(email: str) -> Path:
    return _dir(email) / "brand.json"


def load(email: str) -> dict | None:
    """读品牌资料；没设置过返回 None。"""
    f = _json_path(email)
    if not f.is_file():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - 坏档当没设置
        return None


def save(email: str, fields: dict) -> dict:
    """更新文本字段（全量读改写）。非法值直接忽略，不让用户输坏别人的片。"""
    data = load(email) or {}
    text = fields.get("slogan")
    if isinstance(text, str):
        data["slogan"] = text.strip()[:MAX_SLOGAN]
    opening = fields.get("opening")
    if isinstance(opening, str):
        data["opening"] = opening.strip()[:MAX_OPENING]
    contact = fields.get("contact")
    if isinstance(contact, str):
        data["contact"] = contact.strip()[:MAX_CONTACT]
    for k in ("use_watermark", "endcard"):
        if k in fields:
            data[k] = bool(fields[k])
    accent = fields.get("accent")
    if isinstance(accent, str) and (accent == "" or HEX_RE.match(accent.strip())):
        data["accent"] = accent.strip().upper() or None
    terms = fields.get("terms")
    if isinstance(terms, dict):
        clean = {}
        for word, pinyin in list(terms.items())[:MAX_TERMS]:
            word = str(word).strip()[:12]
            pinyin = str(pinyin).strip().lower()[:40]
            # 只收中文字词 + 声调拼音（管线的同音字替换只对中文生效）
            if word and pinyin and PINYIN_RE.match(pinyin) and any("一" <= c <= "鿿" for c in word):
                clean[word] = pinyin
        data["terms"] = clean
    data.pop("accent_override", None)
    data["updated"] = time.strftime("%Y-%m-%d %H:%M")
    _dir(email).mkdir(parents=True, exist_ok=True)
    _json_path(email).write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")
    return data


def logo_path(email: str) -> Path | None:
    p = _dir(email) / "logo.png"
    return p if p.is_file() else None


def clear_logo(email: str) -> None:
    logo_path(email)
    p = _dir(email) / "logo.png"
    if p.is_file():
        p.unlink()


def set_logo(email: str, data: bytes) -> dict:
    """收 Logo：校验图片、重编码成 ≤600 宽的 PNG、抠主色当品牌色。抛 ValueError 给前端。"""
    if len(data) > MAX_LOGO:
        raise ValueError("Logo 图片别超过 2MB")
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001
        raise ValueError("只认 PNG / JPG / WebP 图片")
    accent = _extract_accent(img)
    img = img.convert("RGBA")
    if img.width > 600:
        img = img.resize((600, round(img.height * 600 / img.width)))
    _dir(email).mkdir(parents=True, exist_ok=True)
    img.save(_dir(email) / "logo.png", "PNG")
    fields = save(email, {"accent": accent or ""})
    return {"accent": fields.get("accent"), "has_logo": True}


def _extract_accent(img) -> str | None:
    """Logo 主色：量化到 48 色，取频次最高且饱和度够的；全灰就取最深的。"""
    try:
        from PIL import Image
        rgba = img.convert("RGBA")
        # 透明底 Logo：把透明像素换成白色再统计，避免透明黑污染主色
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        small = bg.convert("RGB")
        small.thumbnail((96, 96))
        q = small.quantize(colors=48)
        counts = sorted(q.getcolors(), reverse=True)  # [(n, palette_index)]
        palette = q.getpalette()
        best_saturated = None
        best_dark = None
        for n, idx in counts:
            r, g, b = palette[idx * 3:idx * 3 + 3]
            sat = (max(r, g, b) - min(r, g, b)) / 255.0
            lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
            if sat >= 0.30 and n >= 3:
                best_saturated = best_saturated or (n, r, g, b)
            if lum < 200 and (best_dark is None or n > best_dark[0]):
                best_dark = (n, r, g, b)
        pick = best_saturated or best_dark
        if not pick:
            return None
        _, r, g, b = pick
        return f"#{r:02X}{g:02X}{b:02X}"
    except Exception:  # noqa: BLE001 - 取色失败不挡上传
        return None


def for_build(email: str) -> dict | None:
    """出片用的品牌参数（可 JSON 序列化，logo 只带 key，不塞路径）。没设置返回 None。"""
    data = load(email)
    if not data:
        return None
    logo = logo_path(email)
    return {
        "logo_key": _key(email) if logo else None,
        "slogan": data.get("slogan") or "",
        "contact": data.get("contact") or "",
        "opening": data.get("opening") or "",
        "terms": data.get("terms") or {},
        "accent": data.get("accent") or "",
        "use_watermark": data.get("use_watermark", True),
        "endcard": data.get("endcard", True),
    }


# ---------- 我的声音（百炼声音复刻） ----------

def clone_info(email: str) -> dict | None:
    data = load(email) or {}
    c = data.get("clone")
    return c if isinstance(c, dict) and c.get("voice_id") else None


def set_clone(email: str, voice_id: str, sample: bytes) -> dict:
    _dir(email).mkdir(parents=True, exist_ok=True)
    (_dir(email) / "sample.mp3").write_bytes(sample)
    data = load(email) or {}
    data["clone"] = {"voice_id": voice_id, "created": time.strftime("%Y-%m-%d %H:%M")}
    _json_path(email).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return data["clone"]


def clear_clone(email: str) -> str | None:
    data = load(email) or {}
    c = data.pop("clone", None)
    if c:
        data["updated"] = time.strftime("%Y-%m-%d %H:%M")
        _dir(email).mkdir(parents=True, exist_ok=True)
        _json_path(email).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        p = _dir(email) / "sample.mp3"
        if p.is_file():
            p.unlink()
    return (c or {}).get("voice_id")


def resolve_logo(logo_key: str) -> Path | None:
    """logo_key -> 磁盘路径（只认 16 位十六进制，防目录穿越）。"""
    if not re.fullmatch(r"[0-9a-f]{16}", logo_key or ""):
        return None
    p = DIR / logo_key / "logo.png"
    return p if p.is_file() else None


# ---------- 出片侧：把品牌参数压进分镜 ----------

END_CARD_MS = 2900   # 片尾卡时长；整条时间轴派生自 TTS，这里是唯一允许的"额外尾巴"


def _lighten_hex(hex_color: str, amount: float = 0.18) -> str:
    """和 cli._lighten 同一个公式：#rrggbb 亮一档，用于 accentSoft。"""
    s = (hex_color or "").lstrip("#")
    if len(s) != 6:
        return hex_color
    try:
        r, g, b = (int(s[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return hex_color
    mix = lambda c: int(c + (255 - c) * amount)  # noqa: E731
    return f"#{mix(r):02X}{mix(g):02X}{mix(b):02X}"


def apply_to_plan(plan, brand: dict | None) -> dict | None:
    """品牌色压过一切主题色；片尾卡在片尾加 END_CARD_MS。

    在分镜定稿后、算 duration_s 之前调；返回补了 end_card_start_ms 的 brand。
    """
    if not brand:
        return brand
    if brand.get("accent"):
        plan.theme = {"accent": brand["accent"], "accentSoft": _lighten_hex(brand["accent"])}
    has_card = brand.get("endcard", True) and (
        brand.get("slogan") or brand.get("contact") or brand.get("logo_key"))
    if has_card:
        start = int(plan.duration_ms) - 100   # 借最后一镜收尾呼吸的尾巴 100ms 淡入
        plan.duration_ms += END_CARD_MS
        return {**brand, "end_card_start_ms": start}
    return brand
