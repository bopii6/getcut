"""渲染包出口：把导演分镜翻成 props.json，并登记成片台要下载的素材。

画面渲染不在这里：props 交给客户浏览器里的成片台（@remotion/web-renderer +
renderer/src/tool），由它渲帧、编码、混音出带声 mp4。本模块只产 props 与
素材清单——服务器上不装 Node，也不跑 Chrome。
"""
from __future__ import annotations
import json
import re
import shutil
import time
from pathlib import Path

from .planner import Plan, subtitle_units
from .schemas import Content

RENDERER = Path(__file__).resolve().parent.parent / "renderer"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

DISCLAIMER = ""   # 免责声明已整体下线；调用方显式传文案才会显示


def _bundle_file(bundle: Path, rel: str | None) -> Path | None:
    """只返回仍位于素材包内的文件，越界或软链逃逸一律不读。"""
    if not rel:
        return None
    try:
        root = bundle.resolve()
        src = (bundle / rel).resolve()
    except (OSError, RuntimeError):
        return None
    if not src.is_relative_to(root) or not src.is_file():
        return None
    return src


# 素材平台在片尾名单上的展示名（registry.site → 人话；没收录的回落首字母大写）
_SITE_CREDITS = {
    "mixkit": "Mixkit",
    "unsplash": "Unsplash",
    "pexels": "Pexels",
    "pixabay": "Pixabay",
    "flickr": "Flickr",
    "bing": "必应图片",
    "og": "官网公开图",
}


def _used_asset_sites(bundle: Path, used_media: set[str]) -> list[str]:
    """实际用进成片的素材按平台归并。名单只列真用上的——引用名单必须与片子对得上，
    包里有但没选中的素材不上名单。"""
    if not used_media:
        return []
    items = None
    for name in ("registry.json", "manifest.json"):
        f = _bundle_file(bundle, name)
        if not f:
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        items = data.get("assets") if isinstance(data, dict) else data
        break
    if not isinstance(items, list):
        return []
    site_of: dict[str, str] = {}
    for a in items:
        if isinstance(a, dict):
            rel = str(a.get("file", "")).replace("\\", "/").strip("/")
            site = str(a.get("site", "") or "").strip().lower()
            if rel and site:
                # props 里的媒体名把 "/" 整体换成了 "__"（build_props 的 uniq 规则），两边要同归一
                site_of[rel.replace("/", "__")] = site
    prefix = bundle.name + "__"
    sites: list[str] = []
    for uniq in sorted(used_media):
        rel = uniq[len(prefix):] if uniq.startswith(prefix) else uniq
        site = site_of.get(rel)
        if site and site not in sites:
            sites.append(site)
    return [_SITE_CREDITS.get(s, s[:1].upper() + s[1:]) for s in sites]


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
            src = _bundle_file(bundle, shot.asset_path)
            if src:
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
                    src = _bundle_file(bundle, nxt.asset_path)
                    if src:
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
    # ---- 片尾引用名单（电影落幕式，2026-09-28）----
    # 正片放完追加一段静音尾窗：「资料来源」+ 素材平台，像片尾字幕一样亮给观众。
    # 关掉 show_sources 或两条都空 → 不追加尾窗，时长与旧版完全一致。
    credits = None
    if show_sources:
        credit_sources = [str(s).strip() for s in content.sources if str(s or "").strip()]
        asset_sites = _used_asset_sites(bundle, used_media)
        if credit_sources or asset_sites:
            last_end = max([s["endMs"] for s in shots], default=0)
            start_ms = max(int(plan.duration_ms), last_end) + 300
            n_lines = len(credit_sources) + (1 if asset_sites else 0)
            tail_ms = min(6000, max(3600, 2600 + n_lines * 450))
            credits = {"startMs": start_ms, "endMs": start_ms + tail_ms,
                       "sources": credit_sources, "assets": asset_sites}
            # 名单窗里不该再有字幕，照编舞镜头的规矩挖个洞保险
            sub_holes.append((start_ms, start_ms + tail_ms))
    props_out = {
        "durationInFrames": max(int(plan.duration_ms / 1000 * 30) + 21, 30)
                            + (max(0, round((credits["endMs"] - plan.duration_ms) / 1000 * 30))
                               if credits else 0),
        "accent": (plan.theme or {}).get("accent"),
        "accentSoft": (plan.theme or {}).get("accentSoft"),
        "stylePack": getattr(plan, "style_pack", "") or "",
        "headline": _headline_props(content),
        "sources": content.sources if show_sources else [],
        # 有片尾名单时 TSX 会把压角的「资料来源」小字挪进名单（credits=None 自动消失）
        "credits": credits,
        "disclaimer": DISCLAIMER if disclaimer is None else disclaimer,
        "showSubtitles": show_subtitles,
        "template": template,
        "watermark": watermark,
        "shots": shots,
        "clauses": [{"text": c.text, "startMs": round(c.start_ms), "endMs": round(c.end_ms)}
                    for c in plan.clauses],
        # 字幕单位 = 整句（一条最多两行，逗号处折行）。子句那份只留给分镜/剪辑用：
        # 子句是按标点切的（逗号也算边界），直接当字幕会切出"不是一句话"的碎片。
        "captions": [{"text": u["text"], "lines": u["lines"],
                       "startMs": round(u["start_ms"]), "endMs": round(u["end_ms"])}
                      for u in subtitle_units(content.script, plan.clauses)],
        # 编舞镜头（开场/金句/数字卡）时间窗：这些窗里的字幕不出（画面自带大字）
        "subtitleHoles": [[a, b] for a, b in sub_holes],
    }
    if template == "macro":
        # macro：顶部金标题=选题标题；暗背景=导演从素材挑的图（拷进渲染器），没有就用自带 K 线底图。
        # 长标题在标点处取一段做系列名（原片的顶部标题都是 ≤12 字的短栏目名）
        props_out["headline"] = {"lines": [{"text": _macro_series_title(content.title)}]}
        bg_rel = getattr(plan, "bg_asset", None)
        if bg_rel:
            src = _bundle_file(bundle, bg_rel)
            if src:
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
    # 剪映分轨草稿的卡片层取帧清单：一次算清随 props 下发，成片台照它出图。
    # 入场动画走完才是该镜的定妆帧，所以取「镜头末尾退两帧」。
    _dur = props_out["durationInFrames"]
    props_out["draftStills"] = [
        {"id": f"shot_{i:03d}",
         "frame": max(0, min(_dur - 1,
                             max(round(s["startMs"] / 1000 * 30) + 1,
                                 round(s["endMs"] / 1000 * 30) - 2)))}
        for i, s in enumerate(shots)
    ]
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


# ---------- 浏览器成片台：渲染包登记 ----------
# 画面渲染只发生在客户浏览器（web-renderer，见 server._agent_visual 与
# renderer/src/tool）；这里只负责扫出 props 引用的素材并换成 ASCII 名。


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
            # 中文素材包名生成的媒体名含中文（如 美联储加息-素材包-1__images__x.jpg），
            # 白名单只挡路径分隔符；是否真素材由 media_dir 下「文件存在」兜底
            if re.fullmatch(r"[^/\\\n]{3,160}", o) and ".." not in o:
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
