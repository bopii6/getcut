"""阿里云百炼「声音复刻」客户端：用户录音 → 克隆音色 id。

流程（高级档"我的声音"，2026-09-19 按现行 API 真机探针定案）：
  1. 服务器把用户录音用 ffmpeg 转成 mp3（16k 单声道）；
  2. 把 mp3 挂到本机一个随机不可枚举的公开地址（/vc-src/<40位随机hex>.mp3，
     登记完立即删除，另有 30 分钟兜底清扫）；
  3. 调 voice-enrollment（customization）接口 create_voice，让百炼自己来下载：
       {"model":"voice-enrollment",
        "input":{"action":"create_voice","target_model":<TTS_MODEL>,
                 "prefix":"getcut-xxx","url":"https://.../vc-src/xxx.mp3"}}
     ⚠️ 旧版 voice-creation + oss:// 内网地址已废弃，实测一律报
     "url error, please check url"（私有桶 403 / oss 协议不被接受）。
  4. 拿回 voice_id，之后合成走 tts.py 的百炼渠道（pv=voice_id）。
     克隆音色与 target_model 绑定，合成必须用同一个模型。
"""
from __future__ import annotations

import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

import requests

from . import config

BASE = "https://dashscope.aliyuncs.com/api/v1"
ENROLL_URL = BASE + "/services/audio/tts/customization"

# 录音中转目录：登记期间对公网可读（/vc-src/ 路由），登记完即删
VC_SRC_DIR = Path(config.WORKSPACES) / ".videogen-vc-src"


class CloneError(RuntimeError):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}"}


def convert_audio(src: Path, dst_mp3: Path) -> None:
    """任意浏览器录音格式（webm/ogg/m4a）→ 16k 单声道 mp3。"""
    ff = shutil.which("ffmpeg")
    if not ff:
        raise CloneError("服务器缺少 ffmpeg，无法处理录音")
    p = subprocess.run(
        [ff, "-y", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
         "-b:a", "64k", str(dst_mp3)],
        capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not dst_mp3.is_file() or dst_mp3.stat().st_size == 0:
        raise CloneError(f"录音转换失败：{p.stderr[:200]}")


def _sweep_stale(max_age_s: int = 1800) -> None:
    """清扫没来得及删的中转文件（进程重启/请求中断的残留）。"""
    try:
        now = time.time()
        for f in VC_SRC_DIR.glob("*.mp3"):
            if now - f.stat().st_mtime > max_age_s:
                f.unlink(missing_ok=True)
    except OSError:
        pass


def enroll(audio_mp3: Path, display_name: str, public_base: str) -> str:
    """登记音色，返回 voice_id。录音先挂到本机随机公开地址，由百炼来下载。"""
    VC_SRC_DIR.mkdir(parents=True, exist_ok=True)
    _sweep_stale()
    token = secrets.token_hex(20)
    staged = VC_SRC_DIR / f"{token}.mp3"
    shutil.copyfile(audio_mp3, staged)
    prefix = re.sub(r"[^0-9a-zA-Z]", "", (display_name or "").lower())[:10] or "getcut"
    body = {"model": "voice-enrollment",
            "input": {"action": "create_voice", "target_model": config.TTS_MODEL,
                      "prefix": prefix,
                      "url": f"{public_base.rstrip('/')}/vc-src/{token}.mp3"}}
    try:
        # 百炼来本站取录音偶发失败（本站重启窗口/网络抖动）→ 自动重试两次
        for attempt in range(3):
            try:
                r = requests.post(ENROLL_URL, headers={**_headers(), "Content-Type": "application/json"},
                                  json=body, timeout=180)
            except requests.RequestException as e:
                raise CloneError(f"登记请求发不出去：{e}") from None
            try:
                out = r.json()
            except Exception:  # noqa: BLE001 - 非 JSON 响应按原文截断给人看
                out = {}
            voice_id = (out.get("output") or {}).get("voice_id") or ""
            if r.status_code == 200 and voice_id:
                return voice_id
            msg = str(out.get("message") or out.get("code") or r.text[:200])
            if "download" in msg.lower() and attempt < 2:
                time.sleep(2)
                continue
            raise CloneError(f"声音登记失败：{msg}")
        raise CloneError("声音登记失败：重试耗尽")
    finally:
        try:
            staged.unlink(missing_ok=True)
        except OSError:
            pass


def remove(voice_id: str) -> None:
    """删除复刻音色（尽力而为，失败不抛——本地记录照删）。新老接口各试一次。"""
    attempts = [
        (ENROLL_URL, {"model": "voice-enrollment",
                      "input": {"action": "delete_voice", "voice_id": voice_id}}),
        (BASE + "/services/audio/tts/voice-creation",
         {"model": config.TTS_MODEL, "voice_id": voice_id}),
    ]
    for url, body in attempts:
        for method in ("delete", "post"):
            try:
                r = requests.request(method, url, headers=_headers(),
                                     json=body, timeout=30)
                if r.status_code in (200, 201):
                    return
            except Exception:  # noqa: BLE001 - 清理是尽力而为
                pass
