# -*- coding: utf-8 -*-
"""Download every original clip I can reach: his X videos + vidguy demo shorts."""
import os, re, json, subprocess, urllib.request

ROOT = r"E:\getcut"
DEST = os.path.join(ROOT, "ref", "originals")
os.makedirs(DEST, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0 Safari/537.36"
FFMPEG = r"C:\Users\wang\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.0.2-full_build\bin\ffmpeg.exe"
FFPROBE = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")

def get(url, dst):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dst, "wb") as f:
        f.write(r.read())

def probe(path):
    try:
        out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=width,height,r_frame_rate",
                              "-show_entries", "format=duration", "-of", "json", path],
                             capture_output=True, text=True, timeout=60).stdout
        j = json.loads(out)
        st = j["streams"][0]
        return dict(w=st["width"], h=st["height"], fps=st["r_frame_rate"],
                    dur=round(float(j["format"]["duration"]), 2))
    except Exception as e:
        return dict(err=str(e))

items = []

# ---- 1) his own X videos (best variant per id)
html = open(os.path.join(ROOT, "synd.html"), encoding="utf-8", errors="ignore").read()
best = {}
for m in re.finditer(r"https://video\.twimg\.com/amplify_video/(\d+)/vid/avc1/(\d+)x(\d+)/([^\"]+?\.mp4[^\"]*)", html):
    vid, w, h, tail = m.group(1), int(m.group(2)), int(m.group(3)), m.group(4)
    if vid not in best or w > best[vid][0]:
        best[vid] = (w, f"https://video.twimg.com/amplify_video/{vid}/vid/avc1/{w}x{h}/{tail}")
print("his video ids:", len(best))
for i, (vid, (w, url)) in enumerate(sorted(best.items())):
    dst = os.path.join(DEST, f"x_{i:02d}_{vid}.mp4")
    if not os.path.exists(dst):
        try:
            get(url, dst)
        except Exception as e:
            print("  fail", vid, e); continue
    items.append(dict(name=os.path.basename(dst), src="x.com/bizdevelo", url=url, **probe(dst)))
    print("  ok", os.path.basename(dst), items[-1])

# ---- 2) vidguy demo shorts (their production system)
VG = ["https://www.vidguy.ai/influencers/bobby-mechanic-reel.mp4",
      "https://www.vidguy.ai/ai-influencers/keira-morph.mp4",
      "https://www.vidguy.ai/ai-influencers/swap/original.mp4",
      "https://www.vidguy.ai/ai-influencers/swap/keira.mp4",
      "https://www.vidguy.ai/ai-influencers/keira/clip-01.mp4",
      "https://www.vidguy.ai/ai-influencers/keira/clip-02.mp4",
      "https://www.vidguy.ai/ai-influencers/keira/clip-03.mp4"]
for u in VG:
    name = "vg_" + u.rsplit("/", 2)[-2].replace(".mp4", "") + "_" + u.rsplit("/", 1)[-1]
    name = name.replace("//", "_")
    dst = os.path.join(DEST, name)
    if not os.path.exists(dst):
        try:
            get(u, dst)
        except Exception as e:
            print("  fail", u, e); continue
    items.append(dict(name=os.path.basename(dst), src="vidguy.ai demo", url=u, **probe(dst)))
    print("  ok", os.path.basename(dst), items[-1])

json.dump(items, open(os.path.join(DEST, "index.json"), "w", encoding="utf-8"),
          ensure_ascii=False, indent=2)
print("TOTAL", len(items))
