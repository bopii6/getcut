"""状态文件的读写护栏：原子写 + 坏文件自愈。

为什么单独一个模块：users / licenses / registry / jobs 这几个 JSON 是这门生意的
钱袋子。原来的写法是"原地覆盖 + 读坏了当空库"，两件事叠在一起就是：文件一旦坏过
一次，下一个来注册的客户会把整份账号名单冲掉，且没有任何地方能找回。

三层各挡一类事故：
  1. 原子写 —— 先写临时文件再一步换名，任何时刻读到的都是完整旧版或完整新版。
  2. 名单变短先留底 —— 逻辑 bug 想清空账号，会先把原件另存一份。
  3. 读坏了自愈 —— 先把坏文件改名留现场，再从每日备份包里捞回同名文件；
     捞不回来就抛 StoreUnrecoverable 让接口报错，**绝不返回空库**。
"""
from __future__ import annotations

import json
import logging
import os
import secrets
import tarfile
import threading
import time
from pathlib import Path

log = logging.getLogger(__name__)

# 每日备份目录（宿主机 cron 写，容器以只读方式挂进来）。没这个目录时自愈退化为
# "只留现场不恢复"，原子写与留底照常生效 —— 所以本机开发不需要有备份。
BACKUP_DIR = Path(os.environ.get("GETCUT_BACKUPS") or "/opt/videogen/backups")
BACKUP_LOOKBACK = 5           # 自愈时最多往前翻几个备份包
SNAP_KEEP = 10                # "名单变短"留底最多留几份

_HEAL_LOCK = threading.Lock()


class StoreUnrecoverable(RuntimeError):
    """文件坏了且备份也救不回来：此时调用方必须停手，不能写。"""


def atomic_write_text(path: Path, text: str) -> None:
    """同目录临时文件 + fsync + os.replace：换名是原子的，不存在半截文件。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(".%s.tmp-%d-%s" % (path.name, os.getpid(), secrets.token_hex(3)))
    try:
        with tmp.open("w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(4):
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                # Windows 上目标文件正被别的句柄打开时换名会被拒（Linux 不会）；
                # 重试几次仍不行就照抛 —— 宁可报错也不写半截。
                if attempt == 3:
                    raise
                time.sleep(0.05 * (attempt + 1))
            except OSError as exc:
                # 目标是 Docker 单文件挂载点时会 EBUSY：换名换不动挂载点。
                # 这种要改成"挂整个目录"，所以把话说响，别让它躲在 except 里。
                log.error("safestore atomic rename failed", extra={"tmp": tmp.name,
                                                                   "path": str(path)},
                          exc_info=exc)
                raise
    finally:
        tmp.unlink(missing_ok=True)


def write_json(path: Path, data, *, indent: int | None = 1, count=None) -> None:
    """原子写 JSON。给了 count（数记录条数的函数）就顺带做"变短先留底"。"""
    path = Path(path)
    if count is not None:
        _snapshot_if_shrinking(path, data, count)
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent))


def read_json(path: Path, *, default=None, shape=None):
    """读状态文件：文件不存在给 default；读坏了先留现场再从备份自愈。

    shape 是对恢复结果的形状校验（比如"必须有 users 列表"）—— 备份里翻到的东西
    也得像个样子才敢用。
    """
    path = Path(path)
    if not path.is_file():
        return default
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return _heal(path, exc, shape)
    if shape is not None and not shape(data):
        return _heal(path, ValueError("内容不是预期结构"), shape)
    return data


# ---------------------------------------------------------------- 内部

def _snapshot_if_shrinking(path: Path, data, count) -> None:
    if not path.is_file():
        return
    try:
        old = count(json.loads(path.read_text(encoding="utf-8", errors="replace")))
        new = count(data)
    except Exception:  # noqa: BLE001 - 数不出来就不拦，交给原子写
        return
    if not isinstance(old, int) or not isinstance(new, int) or new >= old:
        return
    keep = path.with_name("%s.pre-%s" % (path.name, time.strftime("%Y%m%d-%H%M%S")))
    try:
        keep.write_bytes(path.read_bytes())
    except OSError:
        return
    # 这行是"有人在清空名单"的唯一信号：记录数变少 + 原件留底路径，
    # 出事时靠它判断是逻辑 bug 还是正常编辑。
    log.warning("safestore snapshot kept", extra={"path": path.name, "old": old,
                                                  "new": new, "keep": keep.name})
    stale = sorted(path.parent.glob(path.name + ".pre-*"), key=lambda p: p.name)[:-SNAP_KEEP]
    for p in stale:
        try:
            p.unlink()
        except OSError:
            pass


def _heal(path: Path, exc: Exception, shape):
    with _HEAL_LOCK:
        # 双检：拿到锁时文件可能已被另一个线程修好了
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                if shape is None or shape(data):
                    return data
            except Exception:  # noqa: BLE001
                pass
            stamp = time.strftime("%Y%m%d-%H%M%S")
            bad = path.with_name("%s.bad-%s" % (path.name, stamp))
            try:
                path.replace(bad)
                log.error("safestore file corrupt, scene kept",
                          extra={"path": path.name, "bad": bad.name})
            except OSError:
                bad = None
        got = _from_backup(path.name, shape)
        if got is None:
            raise StoreUnrecoverable(
                "%s 已损坏且没有可用的每日备份，拒绝以空库覆盖" % path.name) from exc
        atomic_write_text(path, json.dumps(got, ensure_ascii=False, indent=1))
        log.warning("safestore restored from daily backup", extra={"path": path.name})
        return got


def _from_backup(name: str, shape):
    """从最近的几个备份包里翻同名文件；翻不到返回 None。"""
    if not BACKUP_DIR.is_dir():
        return None
    packs = sorted((p for p in BACKUP_DIR.glob("*.tar.gz")), key=lambda p: p.name,
                   reverse=True)[:BACKUP_LOOKBACK]
    for pack in packs:
        try:
            with tarfile.open(pack, "r:gz") as tf:
                hits = [m for m in tf.getmembers()
                        if m.isfile() and Path(m.name).name == name]
                for m in hits:
                    f = tf.extractfile(m)
                    if f is None:
                        continue
                    try:
                        data = json.loads(f.read().decode("utf-8"))
                    except Exception:  # noqa: BLE001 - 这个包里这份不行，试下一个
                        continue
                    if shape is None or shape(data):
                        log.info("safestore recovered from pack",
                                 extra={"path": name, "pack": pack.name})
                        return data
        except Exception as exc:  # noqa: BLE001 - 备份包读不动就往前翻
            log.warning("safestore backup pack unreadable",
                        extra={"pack": pack.name}, exc_info=exc)
    return None
