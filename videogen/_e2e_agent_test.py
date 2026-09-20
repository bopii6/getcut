"""E2E：本机渲染台闭环测试（开发机自用，别上生产）。

起一个隔离数据目录的服务器（8622，开放模式），走真实 /api/build 全流程：
LLM 写稿 → TTS 配音 → 素材备料 → planner → **任务挂单等渲染台** → 本机
agent 领取渲染 → 交回画面轨 → 云端混音出成片。

    python _e2e_agent_test.py                             # 窗口1：服务+提交
    node agent/agent.js --server http://127.0.0.1:8622    # 窗口2：渲染台
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

# 开放模式：无令牌 + 空用户文件（.env 的 VIDEOGEN_TOKEN 不覆盖已设环境变量）
os.environ["VIDEOGEN_TOKEN"] = ""
os.environ["VIDEOGEN_USERS_FILE"] = str(
    Path(tempfile.mkdtemp(prefix="gc_e2e_")) / "users.json")

sys.path.insert(0, str(Path(__file__).parent))
from videogen import server as srv  # noqa: E402  （导入即起灶台线程）

# 隔离：任务/项目登记写临时文件，别污染开发数据；OUTPUTS 照旧（成片要看得见）
_tmp = Path(os.environ["VIDEOGEN_USERS_FILE"]).parent
srv.JOBS_FILE = _tmp / "jobs.json"
srv.REG = _tmp / "registry.json"

PORT = 8622
BUNDLE = "bundle-fed-hike"


def main() -> int:
    import urllib.request
    import json
    import uvicorn
    no_submit = "--no-submit" in sys.argv
    ucfg = uvicorn.Config(srv.app, host="127.0.0.1", port=PORT, log_level="warning")
    threading.Thread(target=uvicorn.Server(ucfg).run, daemon=True).start()
    time.sleep(1.5)
    if no_submit:
        print(f"服务已起：浏览器打开 http://127.0.0.1:{PORT} 自己提交素材包；"
              f"另开窗口跑: node agent/agent.js --server http://127.0.0.1:{PORT}",
              flush=True)
        while True:
            time.sleep(3600)
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/api/build",
        data=json.dumps({"bundle": BUNDLE, "sfx": True, "subtitles": True,
                         "sources": True}).encode("utf-8"),
        headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as resp:
        job_id = json.loads(resp.read())["job"]
    print(f"任务 {job_id} 已提交（真实流水线）；另开窗口跑: "
          f"node agent/agent.js --server http://127.0.0.1:{PORT}", flush=True)
    while True:
        time.sleep(8)
        with urllib.request.urlopen(
                f"http://127.0.0.1:{PORT}/api/job/{job_id}", timeout=10) as r:
            j = json.loads(r.read())
        print(f"[{time.strftime('%H:%M:%S')}] stage={j.get('stage')} "
              f"pct={j.get('progress')} via={j.get('render_via')} "
              f"detail={j.get('detail')}", flush=True)
        if j.get("stage") in ("done", "failed", "cancelled"):
            print("成片:", j.get("video"))
            print("结果:", j.get("stage"), j.get("error") or "")
            return 0 if j.get("stage") == "done" else 1


if __name__ == "__main__":
    sys.exit(main())
