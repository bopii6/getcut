"""浏览器成片台（Agent）调度中枢：云端把「出画面」整个交给用户自己的电脑。

产品决策（2026-09-20 拍板）：**渲染只在客户的浏览器里跑，云端与服务器本机都不做渲染**。
用户在浏览器打开成片台页面（renderer/src/tool），它长轮询这里领任务、下载
渲染包（props+素材+音轨）、用 WebCodecs 逐帧渲染并混音、把带声成片传回来。云端灶台
线程在 visual_fn 里阻塞等结果——对 build_render 来说画面渲染仍是一次普通
函数调用。

成片交回之后，成片台还会接着用同一个页面渲出剪映分轨草稿要的那几张 PNG（见
layer_target）：那时任务记录已经摘牌，所以交片时先留一张认领凭据。

唯一的自动救济是「失联收回」：任务被某台成片台领走后心跳停了（渲染中被
杀、断网、合盖），超过 _STALL_SECONDS 没有任何进度就收回来重新排队，最多
_MAX_RECLAIMS 次，超过按失败处理——别让用户对着一个永远转圈的任务干等。
成片台一直不在线则任务停在「待领取」（这就是产品形态：你的片子用你的电脑
渲，成片台没开机就等你开机）。
"""
from __future__ import annotations

import re
import threading
import time
from pathlib import Path

from .schemas import JobCancelled

# 被领取后 10 分钟没有任何进度上报 → 判失联收回（成片台渲染约 1-5 分钟，
# 正常渲染时进度每隔几秒就来，10 分钟静默必然是成片台没了）
_STALL_SECONDS = 600
_MAX_RECLAIMS = 2            # 收回 2 次还失联就按失败处理（第三次不再重试）
_WAIT_PATIENCE = 24 * 3600   # 待领取最长等 24 小时（成片台可能就是没开机）

# 分轨图层的文件名是成片台报上来的，只认这三种写法（挡住一切路径拼接花样）
LAYER_NAME = re.compile(r"^(?:base\.png|cards/shot_[0-9]{3}\.png|texts\.json)$")
_LAYER_TTL = 3600            # 交片后 1 小时内还允许补图层，过期即弃

_JOBS: dict[str, dict] = {}
_DEVICES: dict[str, dict] = {}       # device -> {email-ish owners, last_seen, job}
_LAYER_SLOTS: dict[str, dict] = {}   # jid -> {device, dir, t}：摘牌后的图层认领凭据
_CV = threading.Condition()
on_claim = None                      # server 注入：fn(job_id, device)，更新任务卡


def _jid(job_id: str) -> str:
    return str(job_id)


def register(job_id: str, owner: str | None, props: dict,
             files: dict[str, str], out_path: str,
             audio: tuple[dict, dict[str, str]] | None = None,
             layers_dir: str | None = None) -> None:
    """渲染灶台把一个待渲染任务挂上来：owner=归属邮箱（None=开放模式/无主）。

    audio=(混音计划 meta, {音频相对路径: 本地文件})：只有声明支持「浏览器内
    合成」的成片台（poll 带 x-agent-final: 1）才会收到这部分。
    layers_dir=剪映分轨图层该落到哪个目录（成片台交回成片之后陆续写进来）。
    """
    with _CV:
        all_files = dict(files)
        if audio:
            all_files.update(audio[1])   # 音频文件同画面素材一样走 /agent-media 放行表
        _JOBS[_jid(job_id)] = {
            "owner": owner, "device": None, "status": "waiting",
            "pct": 0, "detail": "等待成片台领取", "props": props,
            "files": all_files, "out_path": out_path,
            "audio": audio, "layers_dir": layers_dir,
            "cancel": threading.Event(), "reclaims": 0,
            "t_reg": time.time(), "t_progress": time.time(), "error": None,
        }
        _CV.notify_all()


def discard(job_id: str) -> None:
    """任务完结（成片已交付/失败/取消）后摘牌。素材文件在主站原地，无需清理。"""
    with _CV:
        j = _JOBS.pop(_jid(job_id), None)
        if j and j["device"]:
            d = _DEVICES.get(j["device"])
            if d and d.get("job") == _jid(job_id):
                d["job"] = None
        _CV.notify_all()


def _claim_locked(owners: list, device: str, want_audio: bool = False) -> dict | None:
    now = time.time()
    for jid in sorted(_JOBS, key=lambda k: _JOBS[k]["t_reg"]):
        j = _JOBS[jid]
        if j["status"] != "waiting" or j["owner"] not in owners:
            continue
        j.update(status="rendering", device=device, pct=0,
                 detail="成片台已领取，正在本机生成", t_progress=now)
        _DEVICES[device] = {"last_seen": now, "job": jid}
        if on_claim is not None:
            try:
                on_claim(jid, device)
            except Exception as exc:  # noqa: BLE001 - 回调绝不能卡住领取
                print(f"agenthub on_claim error: {exc}")
        payload = {"job": jid, "props": j["props"], "files": dict(j["files"])}
        if want_audio and j.get("audio"):
            payload["props"] = {**j["props"], "audio": j["audio"][0]}
        return payload
    return None


def wait_for_job(owners: list, device: str, timeout: float = 25.0,
                 want_audio: bool = False) -> dict | None:
    """成片台长轮询领任务：等到一个就领走返回，超时返回 None（调用方再轮）。"""
    deadline = time.time() + max(0.0, timeout)
    with _CV:
        while True:
            payload = _claim_locked(owners, device, want_audio)
            if payload:
                return payload
            remaining = deadline - time.time()
            if remaining <= 0:
                return None
            _CV.wait(timeout=min(remaining, 5.0))


def file_path(job_id: str, rel: str) -> Path | None:
    """成片台下载渲染包里的一个文件：只放行挂单时登记过的相对路径。"""
    with _CV:
        j = _JOBS.get(_jid(job_id))
        if not j:
            return None
        p = j["files"].get(rel)
    return Path(p) if p and Path(p).is_file() else None


def progress(job_id: str, device: str, pct: int, detail: str | None,
             failed: bool = False, requeue: bool = False) -> dict:
    """成片台上报进度；返回里带 cancel 让它知道该收手了。
    failed=True 是成片台主动报错（Remotion 退出码非 0 等）：任务立刻判失败，
    别让云端傻等失联超时才发现。
    requeue=True 是成片台中途撤了（页面切走/用户放弃）：立即收回重新排队，
    相当于失联收回的主动版。"""
    with _CV:
        j = _JOBS.get(_jid(job_id))
        if not j or j["device"] != device:
            return {"error": "unknown job"}
        if failed:
            j["status"] = "error"
            j["error"] = "成片台渲染失败: " + str(detail or "未知错误")[:3900]
            j["t_progress"] = time.time()
            _CV.notify_all()
            return {"cancel": True}
        if requeue:
            j["reclaims"] += 1
            if j["reclaims"] > _MAX_RECLAIMS:
                j["status"] = "error"
                j["error"] = "成片台反复中途退出，任务已终止。请重新打开成片台页面"
                _CV.notify_all()
                return {"cancel": True}
            j.update(status="waiting", device=None, pct=0,
                     detail="成片台中途离开，任务已重新排队",
                     t_progress=time.time())
            d = _DEVICES.get(device)
            if d and d.get("job") == _jid(job_id):
                d["job"] = None
            _CV.notify_all()
            return {"cancel": True}
        j["pct"] = max(0, min(100, int(pct)))
        if detail:
            j["detail"] = str(detail)[:200]
        j["t_progress"] = time.time()
        d = _DEVICES.get(device)
        if d:
            d["last_seen"] = j["t_progress"]
        return {"cancel": j["cancel"].is_set()}


def upload_target(job_id: str, device: str) -> Path | None:
    """交片第一步：校验身份，给一个临时落盘路径。"""
    with _CV:
        j = _JOBS.get(_jid(job_id))
        if not j or j["device"] != device or j["status"] != "rendering":
            return None
        return Path(str(j["out_path"]) + ".uploading")


def set_crop(job_id: str, device: str, crop: str) -> None:
    """浏览器上报播放器在捕获画面里的裁剪区（x,y,w,h，捕获像素）。"""
    with _CV:
        j = _JOBS.get(_jid(job_id))
        if j and j["device"] == device:
            j["crop"] = str(crop)[:120]


def crop_of(job_id: str) -> str | None:
    with _CV:
        j = _JOBS.get(_jid(job_id))
        return (j or {}).get("crop")


def deliver(job_id: str, device: str, tmp: Path, final: bool = False) -> bool:
    """交片第二步：临时文件原子改名成画面轨，唤醒云端灶台继续混音。

    final=True：交回的不是裸画面轨，而是浏览器已混好音的**完整成片**——
    云端灶台据此跳过混音/封装（见 _agent_visual 的 delivered_final 标记）。
    """
    with _CV:
        j = _JOBS.get(_jid(job_id))
        if not j or j["device"] != device or j["status"] != "rendering":
            return False
        out = Path(j["out_path"])
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp.replace(out)
        j["status"] = "uploaded"
        j["delivered_final"] = bool(final)
        j["pct"] = 100
        j["detail"] = ("成片台渲染合成完成，成片已交回" if final
                       else "成片台渲染完成，正在合成音轨")
        if j.get("layers_dir"):
            _prune_layers(time.time())
            _LAYER_SLOTS[_jid(job_id)] = {"device": device, "dir": j["layers_dir"],
                                          "t": time.time()}
        _CV.notify_all()
    return True


def _prune_layers(now: float) -> None:
    for k in [k for k, v in _LAYER_SLOTS.items() if now - v["t"] > _LAYER_TTL]:
        _LAYER_SLOTS.pop(k, None)


def layer_target(job_id: str, device: str, name: str) -> Path | None:
    """剪映分轨图层（底板/卡片 PNG、文字几何 JSON）的落盘路径。

    这些是成片交回**之后**成片台才陆续渲出来的，那时任务记录已经摘牌，
    所以认的是 deliver() 留下的那张凭据：交片的设备 + 挂单时指定的目录。
    """
    if not LAYER_NAME.match(name):
        return None
    with _CV:
        _prune_layers(time.time())
        rec = _LAYER_SLOTS.get(_jid(job_id))
        if not rec or rec["device"] != device:
            return None
        root = Path(rec["dir"])
    (root / Path(name).parent).mkdir(parents=True, exist_ok=True)
    return root / name


def is_final_delivered(job_id: str) -> bool:
    """wait_result 返回后、discard 之前调用：这次交回来的是不是完整成片。"""
    with _CV:
        j = _JOBS.get(_jid(job_id))
        return bool(j and j.get("delivered_final"))


def wait_result(job_id: str, progress=None, cancel_check=None) -> Path:
    """云端灶台在此阻塞：等成片台交回画面轨，中途桥接进度/取消/失联收回。"""
    deadline = time.time() + _WAIT_PATIENCE
    last = (-1, None)
    while True:
        if cancel_check is not None and cancel_check():
            with _CV:
                j = _JOBS.get(_jid(job_id))
                if j:
                    j["cancel"].set()
                    j["detail"] = "任务已取消"
            raise JobCancelled("任务已被停止")
        with _CV:
            j = _JOBS.get(_jid(job_id))
            if j is None:
                raise RuntimeError("内部错误：渲染任务记录丢失")
            if j["status"] == "uploaded":
                return Path(j["out_path"])
            if j["status"] == "error":
                raise RuntimeError(str(j["error"] or "成片台渲染失败")[:4000])
            now = time.time()
            if (j["status"] == "rendering"
                    and now - j["t_progress"] > _STALL_SECONDS):
                # 成片台失联（被杀/断网/合盖）：收回来重新排队，别的成片台
                # （或它自己回来）可以再领
                j["reclaims"] += 1
                if j["reclaims"] > _MAX_RECLAIMS:
                    j["status"] = "error"
                    j["error"] = "成片台反复失联，任务已终止。请重新打开成片台页面并保持打开"
                    continue
                j.update(status="waiting", device=None, pct=0,
                         detail="成片台失联，任务已重新排队",
                         t_progress=now)
                _CV.notify_all()
            cur = (j["pct"], j["detail"])
        if progress is not None and cur != last:
            last = cur
            progress(cur[0], cur[1])
        if time.time() > deadline:
            raise RuntimeError("等成片台超时（24 小时）：请打开成片台页面领取渲染")
        time.sleep(1.0)


def mark_cancelled(job_id: str) -> None:
    """用户按了停止：成片台下轮上报就会看到 cancel，自己收手。"""
    with _CV:
        j = _JOBS.get(_jid(job_id))
        if j:
            j["cancel"].set()


def snapshot() -> dict:
    """给状态页/排障用：成片台在位情况 + 队列水位。"""
    with _CV:
        now = time.time()
        devices = [{"device": name, "job": d.get("job"),
                    "idle_minutes": int((now - d["last_seen"]) / 60)}
                   for name, d in sorted(_DEVICES.items())]
        waiting = sum(1 for j in _JOBS.values() if j["status"] == "waiting")
        rendering = sum(1 for j in _JOBS.values() if j["status"] == "rendering")
        detail = [{"job": jid, "status": j["status"], "pct": j["pct"],
                   "device": j["device"], "detail": j["detail"],
                   "reclaims": j["reclaims"]}
                  for jid, j in sorted(_JOBS.items(), key=lambda kv: kv[1]["t_reg"])]
    return {"devices": devices, "waiting": waiting, "rendering": rendering,
            "jobs": detail}
