"""自检夹具（开发机自用）：不花钱的「浏览器成片台」端到端验证。

用 9 月美联储加息任务留下的真实 work 目录（props+配音）直接挂一单到 agenthub，
起服务器后浏览器打开 http://127.0.0.1:8622/poc/ 点「开始渲染」即可走全链路：
逐帧渲染 → 浏览器内混音 → final=1 交回 → 本脚本收到成片并打印路径。

    python _tool_selftest.py            # 全片 105s（渲染要几分钟）
    python _tool_selftest.py --bgm      # 带 BGM 版本
"""
import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

os.environ["VIDEOGEN_TOKEN"] = ""
os.environ["VIDEOGEN_USERS_FILE"] = str(Path(tempfile.mkdtemp(prefix="gc_tool_")) / "users.json")
# 9-21 起开放模式要显式开：不开的话这个夹具里那张空账号表 = 成片台领单一律 401，
# 全链路自测会在"点开始渲染"之前就没声没息地卡住。
os.environ["VIDEOGEN_OPEN_MODE"] = "1"

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
from videogen import compose, server as srv  # noqa: E402
from videogen.planner import plan_from_dict  # noqa: E402

WORK = ROOT / "work" / "bundle-fed-hike--b0bd0376014b"
PORT = 8622


def main() -> int:
    import uvicorn

    prep = json.loads((WORK / "prep.json").read_text(encoding="utf-8"))
    props = json.loads((WORK / "props.json").read_text(encoding="utf-8"))
    plan = plan_from_dict(prep["plan"])
    sfx_events = compose.plan_sfx_events(plan, compose.sfx_bank(), mode="full")
    bgm = None
    if "--bgm" in sys.argv:
        music = ROOT / "assets" / "music"
        pack_bgm = {"data": "bgm-electronic", "opinion": "bgm-trap",
                    "profile": "bgm-cinematic", "investigation": "bgm-news"}
        want = pack_bgm.get(getattr(plan, "style_pack", ""), "")
        bgm = next((f for f in sorted(music.glob("*.mp3")) if f.stem.startswith(want)), None)
    audio = {"voice": prep["voice"], "bgm": bgm, "sfx": sfx_events,
             "duration_s": (prep.get("duration_ms") or plan.duration_ms) / 1000.0}
    def run():
        n = 0
        while True:                     # 交付一单自动再挂一单，方便反复验收
            n += 1
            jid = f"selftest{n}"
            out = ROOT / "outputs" / f"_selftest-browser-tool-{n}.mp4"
            out.unlink(missing_ok=True)
            fn = srv._agent_visual(jid)
            try:
                got = fn(props, out, audio=audio)
                print(f"DELIVERED #{n} final={getattr(fn, 'delivered_final', False)} -> {got}",
                      flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"ERROR #{n}: {exc}", flush=True)
                return

    threading.Thread(target=run, daemon=True).start()
    time.sleep(0.5)
    print(f"任务已挂单；浏览器打开 http://127.0.0.1:{PORT}/poc/ 点开始渲染 "
          f"(快速自查可加 ?frames=240 只渲 8 秒)", flush=True)
    uvicorn.run(srv.app, host="127.0.0.1", port=PORT, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
