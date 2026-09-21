"""_browser_safe_video 自测：造坏素材 → 清洗 → 验规格。产物落临时目录，不脏仓库。"""
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from videogen.server import _browser_safe_video  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="browsersafe-selftest-"))


def probe(p):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,width,height,r_frame_rate", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()
    w = h = fps = None
    kinds = []
    for line in r:
        c = [x.strip() for x in line.split(",")]
        kinds.append(c[0])
        if c[0] == "video":
            w, h, fr = int(c[1]), int(c[2]), c[3]
            n, _, d = fr.partition("/")
            fps = int(n) / int(d or 1)
    return {"w": w, "h": h, "fps": fps, "kinds": kinds}


def keyframe_gaps(p):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "frame=key_frame", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True).stdout.strip().splitlines()
    # ffprobe 的 csv 会给首帧补一个尾逗号（"1,"），比较前必须去掉
    idx = [i for i, l in enumerate(out) if l.strip().strip(",") == "1"]
    return [idx[i + 1] - idx[i] for i in range(len(idx) - 1)] or ([len(out)] if len(idx) < 2 else [])


def make(name, size, fps, g, timecode=True):
    p = TMP / name
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
           "-i", f"testsrc2=size={size}:rate={fps}", "-t", "2",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
           "-g", str(g)]
    if timecode:
        cmd += ["-timecode", "01:02:03:04"]
    cmd += ["-movflags", "+faststart", str(p)]
    subprocess.run(cmd, check=True)
    return p


fails = []


def check(label, cond, got):
    print(("  OK   " if cond else "  FAIL ") + label + f" -> {got}")
    if not cond:
        fails.append(label)


for tag, src in [("4k60", make("src4k.mp4", "3840x2160", 60, 500)),
                 ("720p25", make("src720.mp4", "1280x720", 25, 250))]:
    before = probe(src)
    print(f"\n[{tag}] 清洗前 {before} 最大关键帧间隔={max(keyframe_gaps(src))}")
    t0 = time.time()
    out = Path(_browser_safe_video(str(src), TMP / "cache"))
    dt = time.time() - t0
    a = probe(out)
    gaps = keyframe_gaps(out)
    print(f"[{tag}] 清洗后 {a} 耗时={dt:.1f}s "
          f"大小={out.stat().st_size/1048576:.2f}MB 源={src.stat().st_size/1048576:.2f}MB")
    check(f"{tag} 长边<=1920", max(a["w"], a["h"]) <= 1920, f'{a["w"]}x{a["h"]}')
    check(f"{tag} 帧率<=30", a["fps"] <= 30.1, a["fps"])
    check(f"{tag} 只剩一条视频轨", a["kinds"] == ["video"], a["kinds"])
    check(f"{tag} 关键帧间隔<=31", max(gaps) <= 31, max(gaps))
    check(f"{tag} 产物是缓存文件本身", ".b1920f30." in out.name, out.name)
    again = Path(_browser_safe_video(str(src), TMP / "cache"))
    check(f"{tag} 二次调用命中缓存(不重编)",
          str(again) == str(out) and again.stat().st_mtime == out.stat().st_mtime,
          again.name)
    if tag == "720p25":
        check("720p 不被放大", (a["w"], a["h"]) == (1280, 720), f'{a["w"]}x{a["h"]}')

# 干净的小素材必须原样放行：一律重编会让 540p/720p 体积涨六成，
# 而出网只有 3Mbps——那是拿带宽换内存
clean = make("srcclean.mp4", "1280x720", 25, 250, timecode=False)
cp = probe(clean)
check("干净 720p 不重编（只有一条视频轨）", cp["kinds"] == ["video"], cp["kinds"])
same = _browser_safe_video(str(clean), TMP / "cache")
check("干净 720p 原路径返回", same == str(clean), Path(same).name)
big = make("srcbig.mp4", "2560x1440", 25, 250, timecode=False)
bo = Path(_browser_safe_video(str(big), TMP / "cache"))
check("2560 宽被缩到 <=1920", max(probe(bo)["w"], probe(bo)["h"]) <= 1920, bo.name)
check("重编时顺手插密关键帧", max(keyframe_gaps(bo)) <= 31, max(keyframe_gaps(bo)))

img = TMP / "still.jpg"
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                "-i", "color=c=gray:s=640x480", "-frames:v", "1", str(img)], check=True)
check("非视频原样返回", _browser_safe_video(str(img), TMP / "cache") == str(img), img.name)
gone = _browser_safe_video(str(TMP / "不存在.mp4"), TMP / "cache")
check("探测失败退回原路径不拦渲染", gone == str(TMP / "不存在.mp4"), Path(gone).name)

print("\n" + ("全部通过" if not fails else f"失败 {len(fails)} 项: {fails}"))
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if fails else 0)
