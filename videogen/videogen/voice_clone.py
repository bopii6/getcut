"""阿里云百炼「声音复刻」客户端：用户录音 → 克隆音色 id。

流程（高级档"我的声音"）：
  1. 服务器把用户录音用 ffmpeg 转成 mp3（16k 单声道）；
  2. 向百炼拿上传凭证（getPolicy），表单 POST 到 OSS；
  3. 调 voice-creation 登记音色，拿回 voice_id（cosyvoice-v2-* 开头）；
  4. 之后合成就走 tts.py 的百炼渠道（pv=voice_id）。

⚠️ 接口形态按百炼文档实现，上线时第一次真机调用如有字段出入，报错信息会
原样透传给站长排查（本模块不做静默重试以外的隐藏处理）。
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

import requests

from . import config

BASE = "https://dashscope.aliyuncs.com/api/v1"
CREATE_URL = BASE + "/services/audio/tts/voice-creation"


class CloneError(RuntimeError):
    pass


def _headers() -> dict:
    return {"Authorization": f"Bearer {config.DASHSCOPE_API_KEY}"}


def convert_audio(src: Path, dst_mp3: Path) -> None:
    """任意浏览器录音格式（webm/ogg/m4a）→ 16k 单声道 mp3。"""
    ff = None
    import shutil
    ff = shutil.which("ffmpeg")
    if not ff:
        raise CloneError("服务器缺少 ffmpeg，无法处理录音")
    p = subprocess.run(
        [ff, "-y", "-v", "error", "-i", str(src), "-ac", "1", "-ar", "16000",
         "-b:a", "64k", str(dst_mp3)],
        capture_output=True, text=True, timeout=120)
    if p.returncode != 0 or not dst_mp3.is_file() or dst_mp3.stat().st_size == 0:
        raise CloneError(f"录音转换失败：{p.stderr[:200]}")


def _upload(audio: Path) -> str:
    """按百炼的桶规则传录音，返回 voice-creation 要的 audio_url（oss://...）。"""
    r = requests.get(BASE + "/uploads", params={"action": "getPolicy",
                                                "model": config.TTS_MODEL},
                     headers=_headers(), timeout=30)
    if r.status_code != 200:
        raise CloneError(f"拿上传凭证失败：HTTP {r.status_code} {r.text[:200]}")
    pol = (r.json().get("data") or {})
    host, updir = pol.get("upload_host"), pol.get("upload_dir")
    if not host or not updir:
        raise CloneError("上传凭证返回异常（缺 upload_host/upload_dir）")
    key = f"{updir}/{uuid.uuid4().hex}.mp3"
    form = {
        "OSSAccessKeyId": pol.get("oss_access_key_id"),
        "Signature": pol.get("signature"),
        "policy": pol.get("policy"),
        "x-oss-object-acl": pol.get("x_oss_object_acl", "private"),
        "x-oss-forbid-overwrite": pol.get("x_oss_forbid_overwrite", "true"),
        "key": key,
        "success_action_status": "200",
    }
    with open(audio, "rb") as f:
        up = requests.post(host, data=form, files={"file": f}, timeout=120)
    if up.status_code not in (200, 201):
        raise CloneError(f"录音上传失败：HTTP {up.status_code} {up.text[:200]}")
    return f"oss://{key}"


def enroll(audio_mp3: Path, display_name: str) -> str:
    """登记音色，返回 voice_id。"""
    audio_url = _upload(audio_mp3)
    r = requests.post(CREATE_URL, headers={**_headers(), "Content-Type": "application/json"},
                      json={"model": config.TTS_MODEL,
                            "voice_name": display_name or f"user-{uuid.uuid4().hex[:8]}",
                            "audio_url": audio_url},
                      timeout=120)
    body = {}
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        pass
    voice_id = (body.get("output") or {}).get("voice_id") or ""
    if r.status_code != 200 or not voice_id:
        msg = (body.get("message") or body.get("code") or r.text[:200])
        raise CloneError(f"声音登记失败：{msg}")
    return voice_id


def remove(voice_id: str) -> None:
    """删除复刻音色（尽力而为，失败不抛——本地记录照删）。"""
    try:
        requests.delete(CREATE_URL, headers=_headers(),
                        json={"model": config.TTS_MODEL, "voice_id": voice_id}, timeout=30)
    except Exception:  # noqa: BLE001
        pass
