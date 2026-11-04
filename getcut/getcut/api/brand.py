"""品牌套件 + 声音克隆（素材、试听、克隆任务）。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

import asyncio
import re
from pathlib import Path
from fastapi import Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from .. import auth, config, voice_clone
from .. import brand as brand_kit
from .. import tts as tts_mod

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

@router.get("/api/brand")
def brand_get(request: Request):
    """自己的品牌资料（任何登录用户可读，前端好显示引导；写操作才要高级档）。"""
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    return {"brand": brand_kit.load(email) or {}, "premium": auth.tier_at_least(email, "premium"),
            "has_logo": brand_kit.logo_path(email) is not None}
@router.put("/api/brand")
def brand_put(body: dict, request: Request):
    email = ctx._session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "品牌套件是高级版功能", "tier_required": "premium"},
                            status_code=402)
    data = brand_kit.save(email or "", body)
    return {"ok": True, "brand": data}
@router.post("/api/brand/logo")
def brand_logo_upload(request: Request, file: UploadFile = None):
    email = ctx._session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "品牌套件是高级版功能", "tier_required": "premium"},
                            status_code=402)
    if file is None:
        return JSONResponse({"error": "缺少文件"}, status_code=400)
    data = file.file.read(brand_kit.MAX_LOGO + 1)
    try:
        out = brand_kit.set_logo(email or "", data)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"ok": True, **out}
@router.delete("/api/brand/logo")
def brand_logo_delete(request: Request):
    email = ctx._session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "品牌套件是高级版功能", "tier_required": "premium"},
                            status_code=402)
    brand_kit.clear_logo(email or "")
    return {"ok": True}
@router.get("/api/voice-clone")
def voice_clone_get(request: Request):
    email = ctx._session_email(request)
    if not email:
        return JSONResponse({"error": "未登录"}, status_code=401)
    c = brand_kit.clone_info(email)
    return {"premium": auth.tier_at_least(email, "premium"),
            "dashscope": tts_mod.dashscope_ready(),
            "clone": c, "has_voice": bool(c)}
def _clone_worker(raw: bytes, prefix: str, base: str) -> str:
    """阻塞全程（ffmpeg 转码 + 等百炼下载/登记）。必须在工作者线程里跑：
    事件循环若被占死，百炼来 /vc-src/ 取录音时本站无法应答 → 死锁，
    百炼侧报 download audio failed（2026-09-19 用户实录踩过）。"""
    import tempfile
    from .. import voice_clone as vc
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "raw.upload"
        src.write_bytes(raw)
        mp3 = Path(td) / "sample.mp3"
        vc.convert_audio(src, mp3)   # CloneError 由调用方翻译成 400/502
        voice_id = vc.enroll(mp3, prefix, base)
        # 临时目录一退，客户的原始录音就没了：服务器上不留档（见 brand.set_clone）
        # 预热试听缓存：否则用户第一次点试听要现合成（数秒），
        # 超出浏览器"点击后 5 秒内可自动播放"窗口会被拦（实测踩过）
        try:
            pf = ctx._preview_file(voice_id)
            if not pf.exists() or pf.stat().st_size == 0:
                tts_mod.synthesize_preview(voice_id, pf, "嗨，这是你的专属声音，来听听效果。")
        except Exception:  # noqa: BLE001 - 预热失败不影响登记，试听会走现场合成
            pass
        return voice_id
@router.post("/api/voice-clone")
async def voice_clone_create(request: Request, file: UploadFile = None):
    """上传录音（webm/ogg/m4a/mp3）→ ffmpeg 转码 → 百炼声音复刻 → 存 voice_id。

    原始录音只在内存与临时目录里待一小会儿，登记完就随临时目录消失。
    """
    email = ctx._session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "声音克隆是高级版功能", "tier_required": "premium"},
                            status_code=402)
    if not tts_mod.dashscope_ready():
        return JSONResponse({"error": "配音服务尚未配置（等站长开通百炼）"}, status_code=503)
    if file is None:
        return JSONResponse({"error": "缺少录音文件"}, status_code=400)
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        return JSONResponse({"error": "录音别超过 20MB（30 秒足够了）"}, status_code=400)
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
    host = request.headers.get("host") or request.url.netloc
    base = config.PUBLIC_BASE_URL or f"{proto}://{host}"
    try:
        voice_id = await asyncio.to_thread(
            _clone_worker, raw, f"getcut-{brand_kit._key(email)}", base)
    except voice_clone.CloneError as e:
        code = 400 if "录音转换失败" in str(e) or "ffmpeg" in str(e) else 502
        return JSONResponse({"error": str(e)}, status_code=code)
    brand_kit.set_clone(email, voice_id)
    return {"ok": True, "voice_id": voice_id}
@router.get("/vc-src/{name}")
def vc_src(name: str):
    """声音克隆登记期间的中转文件：40 位随机 hex 命名，登记完即删，30 分钟兜底清扫。"""
    if not re.fullmatch(r"[0-9a-f]{40}\.mp3", name or ""):
        return JSONResponse({"error": "not found"}, status_code=404)
    f = voice_clone.VC_SRC_DIR / name
    if not f.is_file():
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(f, media_type="audio/mpeg")
@router.delete("/api/voice-clone")
def voice_clone_delete(request: Request):
    email = ctx._session_email(request)
    if not auth.tier_at_least(email, "premium"):
        return JSONResponse({"error": "声音克隆是高级版功能", "tier_required": "premium"},
                            status_code=402)
    vid = brand_kit.clear_clone(email or "")
    if vid:
        from .. import voice_clone as vc
        vc.remove(vid)   # 尽力而为
    return {"ok": True}
@router.get("/api/brand/logo")
def brand_logo_get(request: Request):
    """自己的 Logo 图（前端预览用）。"""
    email = ctx._session_email(request)
    p = brand_kit.logo_path(email or "")
    if not p:
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(p, media_type="image/png")
