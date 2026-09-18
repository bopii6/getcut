"""Remotion renderer bridge: props.json exporter + visual-track renderer.

Architecture parity with niwo: Python produces structured props (script timing,
shots, designed-overlay copy), Remotion renders the editorial TSX template.
"""
from __future__ import annotations
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path

from .planner import Plan
from .schemas import Content

RENDERER = Path(__file__).resolve().parent.parent / "renderer"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

DISCLAIMER = "本片内容基于公开报道与公开资料整理，观点仅供参考，不构成任何投资建议"


def _report(fn, pct: int, detail: str | None = None) -> None:
    """调用进度回调，兼容只接受 (pct) 的旧签名。"""
    try:
        fn(pct, detail)
    except TypeError:
        try:
            fn(pct)
        except Exception:
            pass
    except Exception:
        pass


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
        if template == "zhigu":
            # 智谷三段式：舞台动作字段直通；开场钩子借一段素材打底（b-roll + 黄胶囊）
            st = o.get("stage") if isinstance(o, dict) else None
            if isinstance(st, dict) and st:
                s["stage"] = st
            if shot.kind == "title_card" and not s.get("media"):
                nxt = next((x for x in plan.shots if x.asset_path), None)
                if nxt and nxt.asset_path:
                    src = bundle / nxt.asset_path
                    if src.is_file():
                        rel = str(nxt.asset_path).replace("\\", "/").strip("/")
                        uniq = f"{bundle.name}__{rel}".replace("/", "__")
                        s["media"] = uniq
                        s["mediaKind"] = "image" if src.suffix.lower() in IMAGE_EXTS else "video"
                        used_media.add(uniq)
                        dst = media_dir / uniq
                        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                            shutil.copyfile(src, dst)
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
                s["overlay"] = {"variant": "compare", "label": o.get("label") or s.get("chapterLabel", "") or "双方对比",
                                "title": o.get("title") or "对峙格局",
                                "subtitle": o.get("subtitle") or "两边的反应开始分化",
                                "badge": o.get("badge", ""),
                                "left": _side(left_raw),
                                "right": _side(right_raw)}
            elif v == "fact":
                s["overlay"] = {"variant": "fact", "label": o.get("label") or "关键事实",
                                "card": {"title": o.get("card_title", ""), "body": o.get("card_body", "")},
                                "badge": o.get("badge", "")}
            else:
                s["overlay"] = {"variant": "statement", "label": o.get("label") or "核心观点",
                                "title": o.get("title", ""), "subtitle": o.get("subtitle", ""),
                                "badge": o.get("badge", ""), "rightNote": o.get("rightNote", ""),
                                "rows": o.get("rows", [])}
        elif shot.overlay:
            # clone 模式：镜头自带完整 overlay（如 statement_media）
            s["overlay"] = {**shot.overlay}
        else:
            s["chapterLabel"] = shot.chapter_label or ""
            s["code"] = f"SHOT {idx:02d}"
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


def render_stills(props: dict, out_dir: Path, prefix: str,
                  ratios=(0.06, 0.30, 0.55, 0.82), quality: int = 82) -> list[Path]:
    """先拍几张关键剧照（分镜预览）：让等待的人看到片子正在长什么样。

    每张 still 由 Remotion 单独渲染，单张约 1–3 秒；失败不影响正式渲染。
    """
    props_path = RENDERER / "props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    cli_js = RENDERER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    node = shutil.which("node")
    if not cli_js.is_file() or not node:
        return []
    total = int(props.get("durationInFrames") or 0)
    if total <= 1:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    made: list[Path] = []
    for i, ratio in enumerate(ratios, start=1):
        frame = max(0, min(total - 1, int(total * ratio)))
        out = out_dir / f"{prefix}-still-{i}.jpg"
        cmd = [node, str(cli_js), "still", "main", str(out),
               "--frame", str(frame), "--props=props.json",
               "--image-format=jpeg", "--jpeg-quality", str(quality), "--log=error"]
        try:
            p = subprocess.run(cmd, cwd=str(RENDERER), capture_output=True,
                               text=True, timeout=120)
            if p.returncode == 0 and out.is_file() and out.stat().st_size > 0:
                made.append(out)
        except Exception:
            pass
    return made


# 渲染器共享状态（props.json / visual_out.mp4）互斥；预览出图与正式渲染共用
_STILL_LOCK = threading.Lock()


def render_still_frame(props: dict, out_path: Path, frame: int,
                       quality: int = 80) -> bool:
    """渲染 props 的第 frame 帧（分镜预览单帧）；成功返回 True。

    用独立的 props_still.json：正式渲染的 props.json 不能被并发改写。
    输出必须是绝对路径——子进程 cwd 是 renderer/，相对路径会写错位置。
    """
    cli_js = RENDERER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    node = shutil.which("node")
    if not cli_js.is_file() or not node:
        return False
    total = int(props.get("durationInFrames") or 0)
    if total <= 1:
        return False
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with _STILL_LOCK:
        props_still = RENDERER / "props_still.json"
        props_still.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
        cmd = [node, str(cli_js), "still", "main", str(out_path),
               "--frame", str(max(0, min(total - 1, frame))),
               "--props=props_still.json",
               "--image-format=jpeg", "--jpeg-quality", str(quality), "--log=error"]
        try:
            p = subprocess.run(cmd, cwd=str(RENDERER), capture_output=True,
                               text=True, timeout=120)
            return p.returncode == 0 and out_path.is_file() and out_path.stat().st_size > 0
        except Exception:
            return False


def render_draft_layers(props: dict, frames: list[dict], base_out: Path, card_dir: Path,
                        texts_out: Path, timeout: int = 2400) -> bool:
    """剪映分轨草稿的两层素材：底板 PNG（一张）+ 每镜卡片 PNG + 文字几何 JSON。

    一次打包、逐镜头渲染；返回是否全部产出。props 会按 exportMode 覆盖。
    """
    script = RENDERER / "scripts" / "draft_layers.mjs"
    node = shutil.which("node")
    if not script.is_file() or not node:
        return False
    props_path = RENDERER / "props_draft.json"
    frames_path = RENDERER / "draft_frames.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    frames_path.write_text(json.dumps(frames, ensure_ascii=False), encoding="utf-8")
    base_out = Path(base_out)
    base_out.parent.mkdir(parents=True, exist_ok=True)
    card_dir = Path(card_dir)
    card_dir.mkdir(parents=True, exist_ok=True)
    texts_out = Path(texts_out)
    cmd = [node, str(script), str(props_path), str(base_out), str(card_dir),
           str(frames_path), str(texts_out)]
    log_path = RENDERER / "draft_stills.log"
    try:
        with open(log_path, "w", encoding="utf-8", errors="replace") as logf:
            subprocess.run(cmd, cwd=str(RENDERER), stdout=logf,
                           stderr=subprocess.STDOUT, timeout=timeout)
    except Exception:
        pass
    ok_base = base_out.is_file() and base_out.stat().st_size > 0
    made = sum(1 for f in frames if (card_dir / f"{f['id']}.png").is_file())
    return ok_base and made == len(frames) and texts_out.is_file()



def render_visual(props: dict, out_path: Path, timeout: int = 1800,
                  progress=None) -> Path:
    props_path = RENDERER / "props.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    cli_js = RENDERER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    node = shutil.which("node")
    if not cli_js.is_file() or not node:
        raise RuntimeError("Remotion CLI not installed; run npm i in renderer/")
    # relative output inside the renderer dir: avoids cmd-shim mangling of
    # non-ASCII absolute paths when forwarding args
    rel_out = "visual_out.mp4"
    # 渲染参数（实测于 4 核云主机，画质不变、只影响编码与并行度）：
    #   image-format=jpeg + q95 —— 逐帧截图的编码开销远低于 png，肉眼无差
    #   x264-preset=veryfast    —— 同画质，文件略大
    #   concurrency             —— 默认只吃一半核；用满核数（Remotion 上限=核数），实测 4 核最快
    conc = max(2, min(4, os.cpu_count() or 2))
    cmd = [node, str(cli_js), "render", "main", rel_out,
           "--props=props.json",
           "--image-format=jpeg", "--jpeg-quality=95",
           "--x264-preset=veryfast", f"--concurrency={conc}"]
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
                            done_f, total_f = int(m.group(1)), int(m.group(2))
                            pct = int(done_f / total_f * 100)
                            if pct > last_pct:
                                last_pct = pct
                                _report(progress, pct,
                                        f"正在渲染画面 {done_f:,} / {total_f:,} 帧")
                            elif done_f >= total_f:
                                # 帧已渲染完，Remotion 在做编码/合轨收尾
                                _report(progress, last_pct, "画面渲染完成，正在编码成片")
                        elif _re.search(r"Bundling|Copying public|Bundled|Packaging", line):
                            # 打包/拷贝阶段：不推进百分比，只更新实况文案
                            _report(progress, max(last_pct, 0), "正在打包渲染工程")
                        elif "time remaining" in line and last_pct >= 0:
                            _report(progress, last_pct, None)
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
