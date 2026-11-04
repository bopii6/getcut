"""线上到底是哪一版 —— 一个能回答这个问题的最小模块。

三个来源按优先级：
  1. 构建参数注入的环境变量（CI 从 git 检出构建镜像时写死，最可信）；
  2. 部署脚本落在代码目录旁的 BUILD_INFO.json（生产是宿主绑挂代码，
     镜像是几天前建的，真正在跑的是**宿主上的这份代码**，所以它必须能自报）；
  3. 就地问 git（本机开发时最方便）。
全都没有就老实说 unknown —— 别拿一个假值糊过去，那正是过去答不上来的原因。
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent        # getcut/
# 生产只把 code/getcut 这一个目录挂进容器（/app/getcut），/app 整目录没挂，
# 所以部署脚本能写的地方只有包目录里头 —— 两处都找一遍。
INFO_FILES = (Path(__file__).resolve().parent / "BUILD_INFO.json", ROOT / "BUILD_INFO.json")


def _git(*args: str) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=str(ROOT.parent),
                           capture_output=True, text=True, timeout=3)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:  # noqa: BLE001 - 没装 git / 不是仓库 / 超时都算"问不出来"
        return ""


def _from_env() -> dict:
    sha = (os.environ.get("GETCUT_BUILD_SHA") or "").strip()
    if not sha or sha == "unknown":
        return {}
    return {"sha": sha,
            "branch": (os.environ.get("GETCUT_BUILD_BRANCH") or "").strip(),
            "built": (os.environ.get("GETCUT_BUILD_DATE") or "").strip(),
            "source": "env"}


def _from_file() -> dict:
    for f in INFO_FILES:
        try:
            raw = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - 文件不存在或坏了都算没有，接着找下一个
            continue
        sha = str(raw.get("sha") or "").strip()
        if sha:
            return {"sha": sha, "branch": str(raw.get("branch") or ""),
                    "built": str(raw.get("built") or ""),
                    "dirty": bool(raw.get("dirty")),
                    "source": "BUILD_INFO.json"}
    return {}


def _from_git() -> dict:
    sha = _git("rev-parse", "--short", "HEAD")
    if not sha:
        return {}
    return {"sha": sha, "branch": _git("rev-parse", "--abbrev-ref", "HEAD"),
            "built": _git("log", "-1", "--format=%cI"),
            "dirty": bool(_git("status", "--porcelain")),
            "source": "git"}


def info() -> dict:
    out = _from_env() or _from_file() or _from_git() or {"sha": "unknown", "source": "none"}
    out.setdefault("dirty", False)
    return out


if __name__ == "__main__":
    print(json.dumps(info(), ensure_ascii=False))
