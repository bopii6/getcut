"""Remotion renderer bridge: props.json exporter + visual-track renderer.

Architecture parity with niwo: Python produces structured props (script timing,
shots, designed-overlay copy), Remotion renders the editorial TSX template.
"""
from __future__ import annotations
import shutil
import subprocess
from pathlib import Path

from .planner import Plan
from .schemas import Content

RENDERER = Path(__file__).resolve().parent.parent / "renderer"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

DISCLAIMER = "本片内容基于公开报道与公开资料整理，观点仅供参考，不构成任何投资建议"


def _headline_props(content: Content) -> dict:
    lines = []
    hook = content.hook_headline
    if hook and hook.lines:
        for raw in hook.lines:
            text = hook.plain(raw)
            spans = hook.highlight_spans(raw)
            highlight = text[spans[0][0]:spans[0][1]] if spans else None
            lines.append({"text": text, "highlight": highlight})
    else:
        lines.append({"text": content.title[:14], "highlight": None})
    return {"lines": lines}


def build_props(bundle: Path, plan: Plan, content: Content,
                title_card: dict, quote_card: dict, theme: dict | None = None,
                show_subtitles: bool = True, show_sources: bool = True,
                disclaimer: str | None = None, template: str = "editorial") -> dict:
    plan.theme = theme or {}
    media_dir = RENDERER / "public" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    # 每个素材包独立命名，避免不同包的同名文件互相覆盖（此前按 src.name 直接拷贝）。
    used_media: set[str] = set()
    shots: list[dict] = []
    for idx, shot in enumerate(plan.shots):
        s: dict = {"kind": shot.kind, "startMs": round(shot.start_ms), "endMs": round(shot.end_ms)}
        if shot.asset_path:
            src = bundle / shot.asset_path
            if src.is_file():
                rel = str(shot.asset_path).replace("\\", "/").strip("/")
                uniq = f"{bundle.name}__{rel}".replace("/", "__")
                s["media"] = uniq
                s["mediaKind"] = "image" if src.suffix.lower() in IMAGE_EXTS else "video"
                used_media.add(uniq)
                dst = media_dir / uniq
                if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                    shutil.copyfile(src, dst)
        o = shot.overlay or {}
        if shot.kind == "title_card":
            s["overlay"] = {"label": title_card.get("label", ""), "keyword": title_card.get("keyword", ""),
                            "code": "SIGNAL / 01"}
        elif shot.kind == "quote_card":
            s["overlay"] = {"label": quote_card.get("label", ""), "quote": quote_card.get("quote", "")}
        elif shot.kind == "callout":
            s["overlay"] = {"label": o.get("label") or s.get("chapterLabel", "") or "关键数据",
                            "number": o.get("number", ""),
                            "caption": o.get("caption", "")}
        elif shot.kind == "panel":
            v = o.get("variant", "fact")
            if v in ("stat", "branches", "timeline", "person"):
                s["overlay"] = {"variant": v, **{k: val for k, val in o.items() if k != "variant"}}
                shots.append(s)
                continue
            if v == "pace":
                s["overlay"] = {"variant": "pace", **{k: val for k, val in o.items() if k != "variant"}}
            elif v == "compare":
                def _side(v):
                    # LLM may return {"head","body"} directly or split fields
                    if isinstance(v, dict):
                        return {"head": str(v.get("head", "")), "body": str(v.get("body", ""))}
                    return {"head": "", "body": str(v or "")}
                left_raw = o.get("left") or {"head": o.get("left_head", ""),
                                             "body": o.get("left_body", "")}
                right_raw = o.get("right") or {"head": o.get("right_head", ""),
                                               "body": o.get("right_body", "")}
                s["overlay"] = {"variant": "compare", "label": o.get("label") or s.get("chapterLabel", "") or "技术封锁",
                                "title": o.get("title") or "芯片变筹码",
                                "subtitle": o.get("subtitle") or "中美反应开始对撞",
                                "badge": o.get("badge", ""),
                                "left": _side(left_raw),
                                "right": _side(right_raw)}
            elif v == "fact":
                s["overlay"] = {"variant": "fact", "label": o.get("label") or "关键事实",
                                "card": {"title": o.get("card_title", ""), "body": o.get("card_body", "")},
                                "badge": o.get("badge", "")}
            else:
                s["overlay"] = {"variant": "statement", "label": o.get("label") or "媒体困局",
                                "title": o.get("title", ""), "subtitle": o.get("subtitle", ""),
                                "badge": o.get("badge", ""), "rightNote": o.get("rightNote", ""),
                                "rows": o.get("rows", [])}
        elif shot.overlay:
            # clone 模式：镜头自带完整 overlay（如 statement_media）
            s["overlay"] = {**shot.overlay}
        else:
            s["chapterLabel"] = shot.chapter_label or ""
            s["code"] = f"{idx:02d} / RACE"
        shots.append(s)
    props_out = {
        "durationInFrames": max(int(plan.duration_ms / 1000 * 30) + 21, 30),
        "accent": (plan.theme or {}).get("accent"),
        "accentSoft": (plan.theme or {}).get("accentSoft"),
        "stylePack": getattr(plan, "style_pack", "") or "",
        "headline": _headline_props(content),
        "sources": content.sources if show_sources else [],
        "disclaimer": DISCLAIMER if disclaimer is None else disclaimer,
        "showSubtitles": show_subtitles,
        "template": template,
        "shots": shots,
        "clauses": [{"text": c.text, "startMs": round(c.start_ms), "endMs": round(c.end_ms)}
                    for c in plan.clauses],
    }
    props_out = {k: v for k, v in props_out.items() if v is not None}
    # 清理本素材包上一轮残留的媒体文件（避免磁盘无界增长）
    prefix = f"{bundle.name}__"
    for old in media_dir.glob(f"{prefix}*"):
        if old.name not in used_media:
            try:
                old.unlink()
            except OSError:
                pass
    return props_out


def render_visual(props: dict, out_path: Path, timeout: int = 1800,
                  progress=None) -> Path:
    import json
    props_path = RENDERER / "props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    cli_js = RENDERER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    node = shutil.which("node")
    if not cli_js.is_file() or not node:
        raise RuntimeError("Remotion CLI not installed; run npm i in renderer/")
    # relative output inside the renderer dir: avoids cmd-shim mangling of
    # non-ASCII absolute paths when forwarding args
    rel_out = "visual_out.mp4"
    cmd = [node, str(cli_js), "render", "main", rel_out,
           "--props=props.json"]
    import re as _re
    import time as _time
    # stdout 重定向到文件而非管道：Remotion 的 Chrome 子进程会继承管道句柄，
    # 用 PIPE 会在渲染结束后拖住 EOF 数分钟（已实测）。
    log_path = RENDERER / "render.log"
    tail = []
    last_pct = -1
    deadline = _time.time() + timeout
    with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
        proc = subprocess.Popen(cmd, cwd=str(RENDERER), stdout=logf,
                                stderr=subprocess.STDOUT)
        pos = 0
        while True:
            if proc.poll() is not None:
                break
            if _time.time() > deadline:
                proc.kill()
                raise subprocess.TimeoutExpired(cmd, timeout)
            _time.sleep(1.0)
            try:
                with open(log_path, "r", encoding="utf-8", errors="replace") as rf:
                    rf.seek(pos)
                    for line in rf:
                        tail.append(line)
                        if len(tail) > 200:
                            tail = tail[-200:]
                        if progress is None:
                            continue
                        m = _re.search(r"Rendered\s+(\d+)\s*/\s*(\d+)", line)
                        if m and int(m.group(2)) > 0:
                            pct = int(int(m.group(1)) / int(m.group(2)) * 100)
                        else:
                            m2 = _re.search(r"(\d{1,3})%", line)
                            pct = int(m2.group(1)) if m2 else -1
                        if pct >= 0 and pct > last_pct:
                            last_pct = pct
                            try:
                                progress(pct)
                            except Exception:
                                pass
                    pos = rf.tell()
            except OSError:
                pass
        proc.wait()
    produced = RENDERER / rel_out
    if proc.returncode != 0 or not produced.is_file():
        raise RuntimeError("remotion render failed:" + chr(10) + "".join(tail)[-4000:])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(produced), str(out_path))
    return out_path
