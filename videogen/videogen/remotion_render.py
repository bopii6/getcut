"""Remotion renderer bridge: props.json exporter + visual-track renderer.

Architecture parity with niwo: Python produces structured props (script timing,
shots, designed-overlay copy), Remotion renders the editorial TSX template.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

from .planner import Plan
from .schemas import Content, JobCancelled

RENDERER = Path(__file__).resolve().parent.parent / "renderer"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

DISCLAIMER = ""   # 免责声明已整体下线；调用方显式传文案才会显示


def _safe_key(key: str | None, default: str = "job") -> str:
    """渲染中间产物文件名里的任务标识：只留安全字符，避免拼路径出事。"""
    k = re.sub(r"[^0-9A-Za-z_-]", "_", str(key or ""))[:48]
    return k or default


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
                disclaimer: str | None = None, template: str = "editorial",
                watermark: bool = True, brand: dict | None = None,
                series: dict | None = None) -> dict:
    plan.theme = theme or {}
    media_dir = RENDERER / "public" / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    # 每个素材包独立命名，避免不同包的同名文件互相覆盖（此前按 src.name 直接拷贝）。
    used_media: set[str] = set()
    sub_holes: list[tuple[int, int]] = []
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
        if template == "macro":
            # 宏观棱镜式：不吃素材，一拍=一章；macroStage 直通（背景在 props 组装处统一给）
            st = o.get("macro") if isinstance(o, dict) else None
            if isinstance(st, dict) and st:
                s["macroStage"] = st
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
        # 片头卡/金句卡：分镜图纸自带文案时优先用它（复刻片、模板样片都是手写的）；
        # 常规出片走 LLM/规则，shot.overlay 是空的，仍用调用方传来的 title_card / quote_card。
        if shot.kind == "title_card":
            # 开场谱三层优先级：镜头自带手写谱（复刻片/样片）> 内容驱动（数字/素材当主角，
            # planner 已把形态挂在 overlay.opening）> 排版谱式兜底。choreo=False 可全关。
            ch = o.get("choreo") if isinstance(o, dict) else None
            opening = o.get("opening") if isinstance(o, dict) else None
            _label = o.get("label") or title_card.get("label", "")
            _kw = o.get("keyword") or o.get("title") or title_card.get("keyword", "")
            _code = o.get("code") or "SIGNAL / 01"
            if ch is None and template == "editorial":
                from .choreo import compose_content_opening, compose_opening
                form = (opening or {}).get("form", "plain") if isinstance(opening, dict) else "plain"
                if form == "media" and not s.get("media"):
                    form = "plain"  # 主角素材缺失（文件不在等），回落排版
                if form in ("number", "media"):
                    ch = compose_content_opening(
                        form, label=_label, keyword=_kw, code=_code,
                        hero_number=(opening or {}).get("hero_number"),
                        has_media=bool(s.get("media")))
                else:
                    ch = compose_opening(f"{bundle.name}|{content.title}",
                                         label=_label, keyword=_kw, code=_code)
            s["overlay"] = {"label": _label, "keyword": _kw, "code": _code}
            if isinstance(ch, dict) and ch.get("cues"):
                s["overlay"]["choreo"] = ch
                # 编舞镜头是设计时刻：烧录字幕再压上来会跟大字撞成一团
                # （2026-09-20 实测开场数字卡两层白字叠字），这个时间窗里的字幕让路
                sub_holes.append((s["startMs"], s["endMs"]))
        elif shot.kind == "quote_card":
            # 片尾谱：手写谱 > 内容驱动（金句压素材/纯排版），同片头三层优先级
            ending = o.get("ending") if isinstance(o, dict) else None
            ch = o.get("choreo") if isinstance(o, dict) else None
            _label = o.get("label") or quote_card.get("label", "")
            _quote = o.get("quote") or o.get("title") or quote_card.get("quote", "")
            if ch is None and template == "editorial":
                from .choreo import compose_ending
                form = (ending or {}).get("form", "plain") if isinstance(ending, dict) else "plain"
                ch = compose_ending(form, label=_label, quote=_quote,
                                    code=o.get("code") or "SIGNAL / 01",
                                    has_media=bool(s.get("media")))
            s["overlay"] = {"label": _label, "quote": _quote}
            if isinstance(ch, dict) and ch.get("cues"):
                s["overlay"]["choreo"] = ch
                # 编舞镜头是设计时刻：烧录字幕再压上来会跟大字撞成一团
                # （2026-09-20 实测开场数字卡两层白字叠字），这个时间窗里的字幕让路
                sub_holes.append((s["startMs"], s["endMs"]))
        elif shot.kind == "callout":
            # 数字卡谱：数字当主角压素材。数字缺失（LLM 没给出）就不编，回落老版式
            ch = o.get("choreo") if isinstance(o, dict) else None
            _label = o.get("label") or s.get("chapterLabel", "") or "关键数据"
            _number = str(o.get("number", "") or "").strip()
            if ch is None and template == "editorial" and _number:
                from .choreo import compose_callout
                ch = compose_callout(label=_label, number=_number,
                                     caption=o.get("caption", ""),
                                     has_media=bool(s.get("media")))
            s["overlay"] = {"label": _label,
                            "number": _number,
                            "caption": o.get("caption", "")}
            if isinstance(ch, dict) and ch.get("cues"):
                s["overlay"]["choreo"] = ch
                # 编舞镜头是设计时刻：烧录字幕再压上来会跟大字撞成一团
                # （2026-09-20 实测开场数字卡两层白字叠字），这个时间窗里的字幕让路
                sub_holes.append((s["startMs"], s["endMs"]))
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
                # 事实卡谱化：字段当主角现场摆（字段缺失就少排，过校验才上）
                if template == "editorial":
                    from .choreo import compose_panel
                    ch2 = compose_panel("fact", s["overlay"])
                    if ch2["cues"]:
                        s["overlay"]["choreo"] = ch2
            else:
                s["overlay"] = {"variant": "statement", "label": o.get("label") or "核心观点",
                                "title": o.get("title", ""), "subtitle": o.get("subtitle", ""),
                                "badge": o.get("badge", ""), "rightNote": o.get("rightNote", ""),
                                "rows": o.get("rows", [])}
                # 观点卡谱化：同事实卡
                if template == "editorial":
                    from .choreo import compose_panel
                    ch2 = compose_panel("statement", s["overlay"])
                    if ch2["cues"]:
                        s["overlay"]["choreo"] = ch2
        elif shot.kind == "footage":
            ch = o.get("choreo") if isinstance(o, dict) else None
            if ch is None and template == "editorial":
                from .choreo import compose_footage
                ch = compose_footage(f"{bundle.name}|{content.title}|{idx}",
                                     label=shot.chapter_label or "")
            if isinstance(ch, dict) and ch.get("cues"):
                s["overlay"] = {"choreo": ch}
        elif shot.overlay and "macro" not in shot.overlay:
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
        "watermark": watermark,
        "shots": shots,
        "clauses": [{"text": c.text, "startMs": round(c.start_ms), "endMs": round(c.end_ms)}
                    for c in plan.clauses],
        # 编舞镜头（开场/金句/数字卡）时间窗：这些窗里的字幕不出（画面自带大字）
        "subtitleHoles": [[a, b] for a, b in sub_holes],
    }
    if template == "macro":
        # macro：顶部金标题=选题标题；暗背景=导演从素材挑的图（拷进渲染器），没有就用自带 K 线底图。
        # 长标题在标点处取一段做系列名（原片的顶部标题都是 ≤12 字的短栏目名）
        props_out["headline"] = {"lines": [{"text": _macro_series_title(content.title)}]}
        bg_rel = getattr(plan, "bg_asset", None)
        if bg_rel:
            src = bundle / bg_rel
            if src.is_file():
                uniq = f"{bundle.name}__macrobg{src.suffix.lower()}"
                dst = media_dir / uniq
                if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                    shutil.copyfile(src, dst)
                used_media.add(uniq)  # 别让下面的残留清理把刚拷的背景删了
                props_out["bgImage"] = uniq
        props_out.setdefault("bgImage", "rep__macro_bg.jpg")
        props_out["channelName"] = "@宏观棱镜"
    if series and series.get("badge"):
        props_out["series"] = {"badge": str(series["badge"])[:24]}
    props_out = {k: v for k, v in props_out.items() if v is not None}
    apply_brand(props_out, bundle, brand)
    # 清理本素材包上一轮残留的媒体文件（避免磁盘无界增长）。
    # 只清"够老"的残留：双通道流水线下，同一素材包可能有别的任务正在渲染、
    # 还引用着这些文件，按 mtime 护栏避开，超过一天的残留才动。
    prefix = f"{bundle.name}__"
    now_ts = time.time()
    for old in media_dir.glob(f"{prefix}*"):
        if old.name in used_media:
            continue
        try:
            if now_ts - old.stat().st_mtime < 86400:
                continue
            old.unlink()
        except OSError:
            pass
    return props_out


def _macro_series_title(title: str) -> str:
    """选题标题 → 顶部系列名：在标点处分段，取最长且 ≤14 字的一段；都太长就截断加省略号。"""
    parts: list[str] = [title]
    for sep in ("：", ":", "，", ",", "｜", "|", "！"):
        parts = [p for seg in parts for p in seg.split(sep)]
    parts = [p.strip() for p in parts if p.strip()]
    fit = [p for p in parts if 4 <= len(p) <= 14]
    if fit:
        return max(fit, key=len)
    return title[:14] + ("…" if len(title) > 14 else "")


def apply_brand(props: dict, bundle: Path, brand: dict | None) -> None:
    """把品牌套装写进 props（已成的 props 也能补，预演复用路径用）。

    Logo 拷进 renderer/public/brand/<key>.png 走 staticFile；水印胶囊 =
    传了 Logo 摆 Logo，配 watermark_text 一起出；片尾卡/品牌色已下线。
    """
    if not brand:
        return
    logo_rel = None
    key = brand.get("logo_key")
    if key:
        from . import brand as brand_kit
        src = brand_kit.resolve_logo(key)
        if src is not None:
            dst_dir = RENDERER / "public" / "brand"
            dst_dir.mkdir(parents=True, exist_ok=True)
            dst = dst_dir / f"{key}.png"
            if not dst.exists() or dst.stat().st_size != src.stat().st_size:
                shutil.copyfile(src, dst)
            logo_rel = f"brand/{key}.png"
    spec: dict = {}
    if logo_rel:
        spec["logo"] = logo_rel
    if brand.get("watermark_text"):
        spec["watermarkText"] = str(brand["watermark_text"])
    if spec:
        props["brand"] = spec


def render_stills(props: dict, out_dir: Path, prefix: str,
                  ratios=(0.06, 0.30, 0.55, 0.82), quality: int = 82) -> list[Path]:
    """先拍几张关键剧照（分镜预览）：让等待的人看到片子正在长什么样。

    每张 still 由 Remotion 单独渲染，单张约 1–3 秒；失败不影响正式渲染。
    """
    props_path = RENDERER / f"props_still_{_safe_key(prefix, 'still')}.json"
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
    props_flag = f"--props={props_path.name}"
    for i, ratio in enumerate(ratios, start=1):
        frame = max(0, min(total - 1, int(total * ratio)))
        out = out_dir / f"{prefix}-still-{i}.jpg"
        cmd = [node, str(cli_js), "still", "main", str(out),
               "--frame", str(frame), props_flag,
               "--image-format=jpeg", "--jpeg-quality", str(quality), "--log=error"]
        try:
            p = subprocess.run(cmd, cwd=str(RENDERER), capture_output=True,
                               text=True, timeout=120)
            if p.returncode == 0 and out.is_file() and out.stat().st_size > 0:
                made.append(out)
        except Exception:
            pass
    try:
        props_path.unlink()
    except OSError:
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
    # 输出路径必须转绝对：node 脚本的 cwd 是 renderer/，相对路径会写到别处，
    # 于是这里检查"文件在不在"永远为假 → 好端端的分轨草稿被判定成"渲染不完整"而退回单轨。
    props_path = (RENDERER / "props_draft.json").resolve()
    frames_path = (RENDERER / "draft_frames.json").resolve()
    props_path.write_text(json.dumps(props, ensure_ascii=False), encoding="utf-8")
    frames_path.write_text(json.dumps(frames, ensure_ascii=False), encoding="utf-8")
    base_out = Path(base_out).resolve()
    base_out.parent.mkdir(parents=True, exist_ok=True)
    card_dir = Path(card_dir).resolve()
    card_dir.mkdir(parents=True, exist_ok=True)
    texts_out = Path(texts_out).resolve()
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



def _kill_proc_tree(proc) -> None:
    """杀掉整棵进程树：Remotion 会 fork 一堆 Chrome 子进程，
    只 kill 父进程会留下一地孤儿继续吃 CPU。Windows 走 taskkill /T。"""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=15)
        else:
            proc.kill()
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


# ---------- 渲染工人节点（远端灶台）客户端 ----------
# 节点侧服务见 rendernode.py：只跑「Remotion 出画面」这一步，混音/封装仍在主站。
# 协议：POST props+素材（multipart）→ 轮询进度 → GET 拉成片；任何失败都抛
# RuntimeError，由调用方（server 的远端灶台线程）回退本地渲染。


def collect_remote_assets(props: dict) -> tuple[dict[str, Path], Path | None]:
    """props 里实际引用的素材：{媒体名: 本地文件}（public/media 下）+ 品牌 logo。

    媒体名靠递归扫 props 字符串值兜底——分镜的 media、macro 的 bgImage、
    智谷 stage 里的 logo 都是一个字符串指到 public/media/<名>，将来模板
    加新的引用字段也不用改这里。
    """
    media: dict[str, Path] = {}
    media_dir = RENDERER / "public" / "media"

    def walk(o) -> None:
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            if re.fullmatch(r"[0-9A-Za-z._-]{3,160}", o) and ".." not in o:
                p = media_dir / o
                if p.is_file():
                    media.setdefault(o, p)

    walk(props)
    logo_path = None
    logo_rel = (props.get("brand") or {}).get("logo")
    if isinstance(logo_rel, str) and re.fullmatch(r"brand/[0-9a-f]{16}\.png", logo_rel):
        p = RENDERER / "public" / logo_rel
        if p.is_file():
            logo_path = p
    return media, logo_path


def _rewrite_media_names(props: dict, rename: dict[str, str]) -> dict:
    """把 props 里的媒体名换成分任务前缀版（节点上多任务互不覆盖）。"""
    def walk(o):
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        if isinstance(o, list):
            return [walk(v) for v in o]
        if isinstance(o, str) and o in rename:
            return rename[o]
        return o
    return walk(props)


def render_visual_remote(props: dict, out_path: Path, *, node_url: str, token: str,
                         job_id: str, timeout: int = 2400,
                         progress=None, cancel_check=None) -> Path:
    """把画面渲染交给渲染节点：上传→轮询→拉回 mp4。失败抛 RuntimeError。"""
    import requests as _rq

    safe = _safe_key(job_id, "job")
    prefix = f"r{safe}__"
    media, logo_path = collect_remote_assets(props)
    rename = {name: f"{prefix}{name}" for name in media}
    props_out = _rewrite_media_names(props, rename)

    _report(progress, 0, "正在把素材传到渲染节点")
    deadline = time.time() + timeout
    upload: list[tuple[str, tuple[str, object, str]]] = []
    handles = []
    try:
        for name, p in media.items():
            fh = open(p, "rb")
            handles.append(fh)
            upload.append(("files", (f"media/{prefix}{name}", fh, "application/octet-stream")))
        if logo_path is not None:
            fh = open(logo_path, "rb")
            handles.append(fh)
            logo_rel = (props.get("brand") or {}).get("logo")
            upload.append(("files", (logo_rel, fh, "application/octet-stream")))
        headers = {"x-node-token": token}
        resp = _rq.post(f"{node_url.rstrip('/')}/v1/render",
                        data={"job": safe, "props": json.dumps(props_out, ensure_ascii=False)},
                        files=upload or None, headers=headers, timeout=(15, 600))
        if resp.status_code != 200:
            raise RuntimeError(f"渲染节点拒收任务 HTTP {resp.status_code}: {resp.text[:300]}")
        remote_id = resp.json().get("job") or safe

        status = None
        while True:
            if time.time() > deadline:
                try:
                    _rq.delete(f"{node_url.rstrip('/')}/v1/render/{remote_id}",
                               headers=headers, timeout=(5, 10))
                except Exception:  # noqa: BLE001
                    pass
                raise RuntimeError(f"渲染节点超时（>{timeout}s）")
            if cancel_check is not None and cancel_check():
                try:
                    _rq.delete(f"{node_url.rstrip('/')}/v1/render/{remote_id}",
                               headers=headers, timeout=(5, 10))
                except Exception:  # noqa: BLE001
                    pass
                raise JobCancelled("任务已被停止")
            time.sleep(1.0)
            try:
                r = _rq.get(f"{node_url.rstrip('/')}/v1/render/{remote_id}",
                            headers=headers, timeout=(5, 15))
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(f"渲染节点失联: {exc}") from exc
            if r.status_code == 404:
                raise RuntimeError("渲染节点不认识这个任务（节点可能刚重启）")
            if r.status_code != 200:
                raise RuntimeError(f"渲染节点状态查询异常 HTTP {r.status_code}")
            info = r.json()
            status = info.get("status")
            if status == "running" or status == "queued":
                _report(progress, max(0, int(info.get("pct") or 0)),
                        info.get("detail") or "节点渲染中")
                continue
            break
        if status != "done":
            raise RuntimeError("渲染节点出错: " + str(info.get("error") or status)[:4000])

        out_path.parent.mkdir(parents=True, exist_ok=True)
        with _rq.get(f"{node_url.rstrip('/')}/v1/render/{remote_id}/video",
                     headers=headers, timeout=(15, 600), stream=True) as v:
            if v.status_code != 200:
                raise RuntimeError(f"拉取成片失败 HTTP {v.status_code}")
            tmp = Path(str(out_path) + ".nodepart")
            with open(tmp, "wb") as f:
                for chunk in v.iter_content(1024 * 512):
                    f.write(chunk)
            if tmp.stat().st_size <= 0:
                raise RuntimeError("渲染节点回传了空文件")
            tmp.replace(out_path)
        return out_path
    finally:
        for fh in handles:
            try:
                fh.close()
            except Exception:  # noqa: BLE001
                pass


def render_visual(props: dict, out_path: Path, timeout: int = 1800,
                  progress=None, key: str = "job",
                  cancel_check=None) -> Path:
    # 渲染中间产物按任务隔离（props/输出/日志各一份）：双通道流水线下允许
    # 多路渲染同时在跑，共用同一份 props.json/visual_out.mp4 会互相覆盖。
    key = _safe_key(key, "job")
    props_path = RENDERER / f"props_{key}.json"
    props_path.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    cli_js = RENDERER / "node_modules" / "@remotion" / "cli" / "remotion-cli.js"
    node = shutil.which("node")
    if not cli_js.is_file() or not node:
        raise RuntimeError("Remotion CLI not installed; run npm i in renderer/")
    # relative output inside the renderer dir: avoids cmd-shim mangling of
    # non-ASCII absolute paths when forwarding args
    rel_out = f"visual_{key}.mp4"
    # 渲染参数（实测于 4 核云主机，画质不变、只影响编码与并行度）：
    #   image-format=jpeg + q95 —— 逐帧截图的编码开销远低于 png，肉眼无差
    #   x264-preset=veryfast    —— 同画质，文件略大
    #   concurrency             —— 默认只吃一半核；用满核数（Remotion 上限=核数），实测 4 核最快
    # 多路并发时每路少开几个 tab，免得内存/CPU 互相挤爆（4 核机器两路各 2 个正合适）
    default_conc = max(2, min(4, os.cpu_count() or 2))
    conc = default_conc
    if os.environ.get("VIDEOGEN_CONCURRENCY"):
        try:
            lanes = max(1, int(os.environ["VIDEOGEN_CONCURRENCY"]))
            conc = max(1, min(default_conc, (os.cpu_count() or 4) // lanes))
        except ValueError:
            pass
    # crf 23：Remotion 默认（18）在动效重的模板上会放飞码率——实测智谷三段式
    # 91 秒的片子能到 81MB（7 Mbps），发出去、传上平台都嫌大。23 在竖屏信息类里
    # 观感几乎无差别，体积能砍到 1/3 左右。
    cmd = [node, str(cli_js), "render", "main", rel_out,
           f"--props={props_path.name}",
           "--image-format=jpeg", "--jpeg-quality=95",
           "--crf=23", "--x264-preset=veryfast", f"--concurrency={conc}",
           # 素材 b-roll 的原声绝不能进片：模板里 <Video> 不带 muted，Remotion 会把
           # 素材原声（如机房嗡嗡声）渲进视觉轨；成片音频一律由 compose.mix_audio
           # 在 Python 侧合成后经 compose.mux 显式 -map 封装。这里静音是第一道闸。
           "--muted"]
    import re as _re
    import time as _time
    # stdout 重定向到文件而非管道：Remotion 的 Chrome 子进程会继承管道句柄，
    # 用 PIPE 会在渲染结束后拖住 EOF 数分钟（已实测）。
    log_path = RENDERER / f"render_{key}.log"
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
            if cancel_check is not None and cancel_check():
                # 用户按了"停止"：杀掉整棵渲染进程树后干净退出
                _kill_proc_tree(proc)
                raise JobCancelled("任务已被停止")
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
    try:
        props_path.unlink()
    except OSError:
        pass
    return out_path
