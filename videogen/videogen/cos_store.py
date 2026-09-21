"""成片外存（腾讯云 COS）：配了桶就把成片交给对象存储，本地那份随后删掉。

为什么要它：服务器出网带宽只有 3Mbps，成片 22–30MB 一条，客户回访下载全挤这根
管子；同时系统盘 40G 会被成片无限吃掉。COS 两头都解：下载走对象存储自己的出口，
本地盘不再长成片。

没配桶（本机开发、新机器还没开 COS）时 `enabled()` 为 False，所有调用点自动退回
本地文件，功能一模一样 —— 所以这套代码不要求生产必须先有 COS。
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from urllib.parse import quote

BUCKET = (os.environ.get("VIDEOGEN_COS_BUCKET") or "").strip()
REGION = (os.environ.get("VIDEOGEN_COS_REGION") or "ap-beijing").strip()
SECRET_ID = (os.environ.get("VIDEOGEN_COS_SECRET_ID") or "").strip()
SECRET_KEY = (os.environ.get("VIDEOGEN_COS_SECRET_KEY") or "").strip()
PREFIX = (os.environ.get("VIDEOGEN_COS_PREFIX") or "films").strip().strip("/") or "films"
# 签名链接有效期：够客户点完一次下载 + 换台机器再点一次，又不至于变成永久公开链接
URL_TTL = max(600, int(os.environ.get("VIDEOGEN_COS_URL_TTL") or 7200))

_client = None
_lock = threading.Lock()


def enabled() -> bool:
    return bool(BUCKET and REGION and SECRET_ID and SECRET_KEY)


def _cli():
    global _client
    if _client is None:
        from qcloud_cos import CosConfig, CosS3Client
        _client = CosS3Client(CosConfig(Region=REGION, SecretId=SECRET_ID,
                                        SecretKey=SECRET_KEY, Token=None, Scheme="https"))
    return _client


def key_for(job_id: str, name: str) -> str:
    """按任务号前缀分目录：桶里好翻，也避免同名成片互相覆盖。"""
    return "%s/%s/%s" % (PREFIX, str(job_id)[:8], Path(name).name)


def upload(local: Path, key: str) -> bool:
    """成功 True。失败只记一行并返回 False —— 调用方保留本地文件，功能不受影响。"""
    if not enabled() or not local.is_file():
        return False
    try:
        with _lock:
            cli = _cli()
            cli.upload_file(Bucket=BUCKET, Key=key, LocalFilePath=str(local),
                            PartSize=16, MAXThread=3, EnableMD5=False)
        return True
    except Exception as exc:  # noqa: BLE001 - 外存失败不能拖垮出片
        print("cos upload failed [%s]: %s" % (key, exc))
        return False


def fetch(key: str, local: Path) -> bool:
    """把成片拉回本地临时路径（剪映草稿、封面这类要真文件的场合用）。"""
    if not enabled():
        return False
    try:
        local.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            cli = _cli()
        # download_file 在 client 上（get_object 只返回一个 dict，没有这个方法）
        cli.download_file(Bucket=BUCKET, Key=key, DestFilePath=str(local))
        return local.is_file()
    except Exception as exc:  # noqa: BLE001
        print("cos fetch failed [%s]: %s" % (key, exc))
        return False


def sign_url(key: str, download_name: str | None = None) -> str:
    """限时签名链接。带上 download 文件名，浏览器直接存盘而不是原地播放。

    文件名一律走 RFC 5987 的 filename*= 写法：成片名基本都带中文，裸中文塞进
    响应头不合法，经代理/CDN 可能被mung成乱码。
    """
    params = {}
    if download_name:
        params["response-content-disposition"] = \
            "attachment; filename*=UTF-8''%s" % quote(download_name)
    with _lock:
        return _cli().get_presigned_url(Method="GET", Bucket=BUCKET, Key=key,
                                        Expired=URL_TTL, Params=params or None)


def drop(key: str) -> None:
    if not enabled():
        return
    try:
        with _lock:
            _cli().delete_object(Bucket=BUCKET, Key=key)
    except Exception as exc:  # noqa: BLE001
        print("cos delete failed [%s]: %s" % (key, exc))


def archive(job_id: str, local: Path) -> str | None:
    """上传并返回 cos key；失败返回 None（调用方继续用本地文件）。"""
    key = key_for(job_id, local.name)
    t0 = time.time()
    if upload(local, key):
        print("cos archived %s (%.1fMB / %.1fs)" % (key, local.stat().st_size / 1048576,
                                                    time.time() - t0))
        return key
    return None
