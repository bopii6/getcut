"""safestore 自检：跑 `python _tools/safestore_check.py`，全绿打印 PASS。

覆盖状态文件护栏的四件事：原子写、名单变短先留底、坏文件从备份自愈、
坏且无备份时拒绝以空库覆盖。不依赖 pytest，服务器上也能直接跑同一份。
"""
from __future__ import annotations

import json
import shutil
import sys
import tarfile
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from videogen import safestore  # noqa: E402

USERS = {"users": [{"email": "a@x.com", "tier": "premium"},
                   {"email": "b@x.com", "tier": "basic"},
                   {"email": "c@x.com", "tier": "premium"}]}
_shape = lambda d: isinstance(d.get("users"), list)  # noqa: E731
_count = lambda d: len(d.get("users") or [])          # noqa: E731


def _pack(backup_dir: Path, name: str, data: dict, day: str) -> None:
    """按备份脚本的打包方式造一个包：<backups>/videogen-data-<day>.tar.gz"""
    stage = backup_dir / "stage"
    (stage / "data").mkdir(parents=True, exist_ok=True)
    (stage / "data" / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with tarfile.open(backup_dir / ("videogen-data-%s.tar.gz" % day), "w:gz") as tf:
        tf.add(stage / "data" / name, arcname="data/" + name)
    shutil.rmtree(stage)


def t1_atomic_read_never_sees_half(tmp: Path) -> str:
    f = tmp / "jobs.json"
    safestore.write_json(f, {"big": [{"x": i} for i in range(400)]}, indent=None)
    stop, bad, shared, ok_read = threading.Event(), [], [], []

    def reader():
        n = 0
        while not stop.is_set():
            try:
                json.loads(f.read_text(encoding="utf-8"))
                ok_read.append(n)
            except json.JSONDecodeError as exc:
                bad.append("第 %d 次读到半截文件: %s" % (n, exc))
            except PermissionError:
                # Windows 独占共享：换名的一瞬间读方会被拒。Linux 上 rename 是原子的，
                # 读方永远拿到完整旧版或完整版 —— 这里只记次数，不算失败。
                shared.append(n)
            n += 1

    th = threading.Thread(target=reader, daemon=True)
    th.start()
    for _r in range(25):
        try:
            safestore.write_json(f, {"big": [{"x": i, "pad": "y" * 40} for i in range(400)]},
                                 indent=None)
        except PermissionError:
            pass          # Windows：读方句柄还没放，换名被拒。Linux 生产不会走到
        time.sleep(0.01)
    time.sleep(0.3)
    stop.set()
    th.join(timeout=5)
    if bad:
        raise AssertionError(bad[0])
    return ("25 次重写，并发读到 %d 次全部完整%s"
            % (len(ok_read),
               "（另有 %d 次被 Windows 独占共享挡回，Linux 无此现象）" % len(shared)
               if shared else ""))


def t2_shrink_snapshot(tmp: Path) -> str:
    f = tmp / ".videogen-users.json"
    safestore.write_json(f, USERS, count=_count)
    safestore.write_json(f, {"users": USERS["users"][:1]}, count=_count)   # 3 → 1
    snaps = sorted(f.parent.glob(".videogen-users.json.pre-*"))
    if not snaps:
        raise AssertionError("没有生成 .pre-* 留底")
    kept = json.loads(snaps[0].read_text(encoding="utf-8"))
    if len(kept.get("users") or []) != 3:
        raise AssertionError("留底内容不是覆盖前的 3 条，而是 %d 条" % len(kept.get("users") or []))
    return "3→1 时原件已留底（%s，3 条账号）" % snaps[0].name


def t3_heal_from_backup(tmp: Path) -> str:
    backups = tmp / "backups"
    backups.mkdir()
    old = safestore.BACKUP_DIR
    safestore.BACKUP_DIR = backups
    try:
        name = ".videogen-users.json"
        _pack(backups, name, USERS, "20260920")
        f = tmp / name
        f.write_text('{"users": [{"email": "a@x.c', encoding="utf-8")   # 半截 JSON
        got = safestore.read_json(f, default={}, shape=_shape)
        if [u["email"] for u in got["users"]] != [u["email"] for u in USERS["users"]]:
            raise AssertionError("恢复出来的名单不对")
        if not list(f.parent.glob(name + ".bad-*")):
            raise AssertionError("坏文件没被留现场")
        if json.loads(f.read_text(encoding="utf-8")).get("users") is None:
            raise AssertionError("原位没写回好数据")
        return "半截文件已留现场并从备份包恢复（3 条账号回到原位）"
    finally:
        safestore.BACKUP_DIR = old


def t4_refuse_empty_overwrite(tmp: Path) -> str:
    backups = tmp / "backups2"
    backups.mkdir()
    old = safestore.BACKUP_DIR
    safestore.BACKUP_DIR = backups
    try:
        f = tmp / ".videogen-licenses.json"
        raw = '{"codes": [xx'            # 坏了，且没有任何备份
        f.write_text(raw, encoding="utf-8")
        try:
            safestore.read_json(f, default={"codes": []},
                                shape=lambda d: isinstance(d.get("codes"), list))
        except safestore.StoreUnrecoverable as exc:
            still = [p for p in f.parent.glob(".videogen-licenses.json.bad-*")]
            if not still:
                raise AssertionError("抛错但没留现场") from exc
            if still[0].read_text(encoding="utf-8") != raw:
                raise AssertionError("现场内容被改过") from exc
            if f.exists():
                raise AssertionError("原位不该被空库覆盖") from exc
            return "无备份时抛 StoreUnrecoverable，坏原件留现场、没被空库覆盖"
        raise AssertionError("本该抛错却返回了空库")
    finally:
        safestore.BACKUP_DIR = old


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="safestore-check-"))
    ok = True
    try:
        for t in (t1_atomic_read_never_sees_half, t2_shrink_snapshot,
                  t3_heal_from_backup, t4_refuse_empty_overwrite):
            try:
                print("  PASS  %-26s %s" % (t.__name__.split("_", 1)[1][:24], t(tmp)))
            except Exception as exc:  # noqa: BLE001
                ok = False
                print("  FAIL  %-26s %s" % (t.__name__.split("_", 1)[1][:24], exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
