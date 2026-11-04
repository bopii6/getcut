"""声音 / BGM / SFX / 模板 / 字体等可复用素材。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import html
import json
from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from .. import auth
from .. import brand as brand_kit
from .. import tts as tts_mod
from ..schemas import Content, Manifest

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

@router.get("/api/voices")
def voices_list(request: Request):
    """音色目录：配了百炼密钥就是 CosyVoice 音色；没配则退回 edge 内置目录
    （界面展示什么，合成时就真的用什么，不挂羊头卖狗肉）。"""
    ready = tts_mod.dashscope_ready()
    if not ready:
        legacy = tts_mod.LEGACY_EDGE_VOICES
        return {"voices": [{"id": k, "label": v, "provider": "edge"} for k, v in legacy.items()],
                "dashscope": False, "default": "zh-CN-YunxiNeural"}
    items = [{"id": vid, "label": v.get("label", vid), "provider": "dashscope"}
             for vid, v in tts_mod.load_voices().items()]
    # 我的声音（声音复刻）：克隆过就放进音色列表最前面
    email = ctx._session_email(request)
    if email and auth.tier_at_least(email, "premium") and brand_kit.clone_info(email):
        items.insert(0, {"id": "@clone", "label": "我的声音 · 克隆", "provider": "dashscope"})
    return {"voices": items, "dashscope": True, "default": tts_mod.VOICE}
@router.get("/api/voice-preview")
def voice_preview(request: Request, voice: str = "xiaoxia"):
    """音色试听：合成一句短样，按音色+渠道缓存（首次约 1-2 秒）。"""
    if voice == "@clone":
        # 确认页里「我的声音」以 @clone 占位；试听必须换成当前用户真实的克隆音色 id
        email = ctx._session_email(request)
        c = brand_kit.clone_info(email) if email else None
        if not c or not c.get("voice_id"):
            return JSONResponse({"error": "还没有克隆声音，先到「我的 → 品牌套装」里录制"},
                                status_code=404)
        voice = c["voice_id"]
    elif voice not in tts_mod.load_voices():
        # 目录外的音色 id 只认调用者自己克隆的那一个：光知道别人的 id 借不到他的声音
        email = ctx._session_email(request)
        c = brand_kit.clone_info(email) if email else None
        if not c or c.get("voice_id") != voice:
            return JSONResponse({"error": "音色不存在"}, status_code=404)
    f = ctx._preview_file(voice)
    if not f.exists() or f.stat().st_size == 0:
        try:
            tts_mod.synthesize_preview(
                voice, f, "大家好，这是一段配音试听，听听这个声音合不合适。")
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"error": f"试听合成失败：{e}"}, status_code=502)
    return FileResponse(f, media_type="audio/mpeg")
@router.get("/api/bgm/{name}")
def bgm_file(name: str):
    """BGM 试听/播放：只允许 assets/music 下的 mp3。"""
    f = (ctx.ROOT / "assets" / "music" / name).resolve()
    music = (ctx.ROOT / "assets" / "music").resolve()
    if music not in f.parents or f.suffix.lower() != ".mp3" or not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="audio/mpeg")
@router.get("/api/sfx/{name}")
def sfx_file(name: str):
    """音效试听/播放：只允许 assets/sfx 下的音频。"""
    f = (ctx.ROOT / "assets" / "sfx" / name).resolve()
    root = (ctx.ROOT / "assets" / "sfx").resolve()
    if root not in f.parents or f.suffix.lower() not in (".mp3", ".wav", ".m4a") or not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="audio/mpeg")
# 音效分类的中文名与"什么时候响"，试听页按这个分组
_SFX_LABEL = {
    "open": ("开场", "片头起手那一下"),
    "cut": ("镜头切换", "每换一个画面轻切一声"),
    "card": ("卡片弹出", "设计卡/胶囊/榜单弹出来时"),
    "number": ("数字落点", "数字、数字卡冒出来时"),
    "emphasis": ("重点强调", "金句、要用力砸一下的地方"),
    "end": ("收尾", "最后收住"),
}
@router.get("/sfx-preview", response_class=HTMLResponse)
def sfx_preview():
    """音效试听页：按分类列出库里的每一条，点一下就能听。

    存在的理由：出片的人（也就是我）听不到声音，音效"像不像那么回事"只能由人耳朵验收。
    换音效 = 把 mp3 丢进 assets/sfx/ 并在 library.json 加一条，这里会自动出现。
    """
    lib = ctx.ROOT / "assets" / "sfx"
    items: list[dict] = []
    try:
        items = json.loads((lib / "library.json").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        items = []
    rows: dict[str, list[str]] = {}
    for it in items:
        cat = it.get("category") or "其他"
        if cat == "legacy":
            continue
        f = lib / it["file"]
        if not f.is_file():
            continue
        rows.setdefault(cat, []).append(
            f'<li><audio controls preload="none" src="/api/sfx/{html.escape(it["file"])}"></audio>'
            f'<b>{html.escape(it["file"])}</b>'
            f'<small>{it.get("bytes", 0) // 1024} KB · {html.escape(str(it.get("source", "")))}</small></li>')
    order = [c for c in _SFX_LABEL if c in rows] + [c for c in rows if c not in _SFX_LABEL]
    body = "".join(
        f'<section><h2>{html.escape(_SFX_LABEL.get(c, (c, ""))[0])}'
        f'<small>{html.escape(_SFX_LABEL.get(c, ("", ""))[1])}　{len(rows[c])} 条</small></h2>'
        f'<ul>{"".join(rows[c])}</ul></section>'
        for c in order)
    total = sum(len(v) for v in rows.values())
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>音效试听 · 共 {total} 条</title><style>
body{{margin:0;padding:32px 24px 64px;background:#12141c;color:#e3e5f0;
  font:14px/1.6 "Microsoft YaHei","Segoe UI",sans-serif}}
h1{{font-size:22px;margin:0 0 6px}}p.sub{{color:#98a0b6;margin:0 0 26px}}
h2{{font-size:16px;margin:30px 0 12px;display:flex;align-items:baseline;gap:12px}}
h2 small{{font-weight:400;color:#98a0b6;font-size:12px}}
ul{{list-style:none;margin:0;padding:0;display:grid;gap:10px}}
li{{display:flex;align-items:center;gap:14px;background:#1a1d29;border:1px solid #2a2f3f;
  border-radius:10px;padding:12px 16px}}
li b{{font-size:13px;font-weight:600}}li small{{color:#98a0b6;font-size:12px;margin-left:auto}}
audio{{height:34px}}
</style></head><body>
<h1>音效试听</h1>
<p class="sub">共 {total} 条。哪条不合适就在对话里点它的文件名，我换掉。
音效是"什么时候弹出一个东西就响一下"，音量统一压在解说之下。</p>
{body}</body></html>"""
@router.get("/templates/{name}")
def template_thumb(name: str):
    """模板素材：真实静帧封面 tpl-<id>.png，和样片 sample-<id>.mp4（选择器里点一下就能看）。

    由 tools/make_template_previews.py 一键生成，模板改了就重跑那条命令。
    """
    root = (ctx.STATIC / "templates").resolve()
    f = (root / name).resolve()
    if not f.is_file() or root not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    media = "video/mp4" if f.suffix.lower() == ".mp4" else "image/png"
    return FileResponse(f, media_type=media)
@router.get("/fonts/{name}")
def font(name: str):
    """前端自托管的字体子集（展示字，与成片同款）。"""
    root = (ctx.STATIC / "fonts").resolve()
    f = (root / name).resolve()
    if not f.is_file() or root not in f.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="font/ttf")
@router.get("/api/bundles")
def bundles(request: Request):
    return [b for b in ctx._find_bundles() if ctx._bundle_visible(b["name"], request)]
@router.get("/api/templates")
def templates():
    """可选渲染模板（前端配置页据此渲染选择器）。"""
    return {"default": ctx.DEFAULT_TEMPLATE,
            "templates": [{"id": k, "name": v} for k, v in ctx.TEMPLATES.items()]}
@router.get("/api/bundle/{name}")
def bundle_detail(name: str, request: Request):
    d = (ctx.WORKSPACES / name).resolve()
    if not d.is_dir() or ctx.WORKSPACES.resolve() not in d.parents:
        return JSONResponse({"error": "not found"}, status_code=404)
    if not ctx._bundle_visible(name, request):
        return JSONResponse({"error": "not found"}, status_code=404)
    content = Content.load(d / "content.json")
    assets = []
    if (d / "manifest.json").is_file():
        m = Manifest.load(d / "manifest.json")
        assets = [a.__dict__ for a in m.assets]
    hook = content.hook_headline
    hook_lines = []
    if hook and hook.lines:
        for ln in hook.lines:
            spans = hook.highlight_spans(ln)
            hook_lines.append({
                "text": hook.plain(ln),
                "highlight": hook.plain(ln)[spans[0][0]:spans[0][1]] if spans else "",
            })
    return {
        "name": name,
        "title": content.title,
        "script": content.script,
        "estSeconds": round(len(content.script) / 6),
        "hookLines": hook_lines,
        "sources": content.sources,
        "pronunciations": content.pronunciations,
        "notes": content.notes,
        "assets": assets,
        "mediaBase": f"/media/{name}",
    }
@router.get("/api/music")
def music_library():
    """BGM 库：assets/music/*.mp3 + library.json（情绪标签）。"""
    d = ctx.ROOT / "assets" / "music"
    lib = {}
    mf = d / "library.json"
    if mf.is_file():
        try:
            lib = {x["file"]: x for x in json.loads(mf.read_text(encoding="utf-8"))}
        except Exception:
            lib = {}
    out = []
    for f in sorted(d.glob("*.mp3")):
        info = lib.get(f.name, {})
        out.append({"file": f"assets/music/{f.name}", "name": f.stem,
                    "mood": info.get("mood", ""), "genre": info.get("genre", "")})
    return out
@router.get("/api/latest")
def latest(request: Request):
    """最近成片名（前端已不用；留给管理员巡检，普通用户不给跨用户文件名）。"""
    if not ctx._open_mode() and not ctx._is_adminish(request):
        return JSONResponse({"error": "not found"}, status_code=404)
    outs = sorted(ctx.OUTPUTS.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) \
        if ctx.OUTPUTS.is_dir() else []
    if not outs:
        return {"video": None}
    f = outs[0]
    jid = f.stem.rsplit("-", 1)[-1]
    return {"video": f.name, "job": jid, "mtime": int(f.stat().st_mtime)}
