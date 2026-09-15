#!/usr/bin/env python3
"""为「AI减速之争2.0」素材包采集素材：Wikimedia人物 + Pexels/Pixabay场景图 + Mixkit/Pexels视频。"""
import json
import re
import subprocess
import time
import urllib.request
from pathlib import Path

BUNDLE = Path(r'E:/短视频生成/bundle-ai-slowdown-2')
META = BUNDLE / '_assets_meta.json'
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PEXELS = (Path(r'E:/短视频生成/videogen/pexels_key.txt')).read_text(encoding='utf-8').strip()
PIXABAY = (Path(r'E:/短视频生成/videogen/pixabay_key.txt')).read_text(encoding='utf-8').strip()

meta = json.loads(META.read_text(encoding='utf-8')) if META.is_file() else []


def _num():
    nums = [int(m.group(1)) for m in (re.search(r'/(\d+)-', e['file']) for e in meta) if m]
    return max(nums, default=0) + 1


def _save(sub: str, slug: str, data: bytes, src_url: str, license_: str, summary: str,
          tags: list, anchor: str) -> str | None:
    n = _num()
    head = data[:16]
    if len(data) < 5000 or head[:1] == b'<' or head[:5].lower() == b'<!doc':
        return None
    ext = ('.jpg' if head[:3] == b'\xff\xd8\xff' else '.png' if head[:8] == b'\x89PNG\r\n\x1a\n'
           else '.mp4' if head[4:8] == b'ftyp' else '.webm' if head[:4] == b'\x1aE\xdf\xa3' else '')
    if not ext:
        return None
    name = f"{n:02d}-{slug}{ext}"
    (BUNDLE / sub / name).write_bytes(data)
    meta.append({"file": f"{sub}/{name}", "source_url": src_url, "license": license_,
                 "summary": summary, "tags": tags, "script_anchor": anchor})
    return name


def commons(slug, query, want, summary, tags, anchor, min_w=900):
    """Wikimedia 图片（CC/公有领域），只取横构图。"""
    import urllib.parse
    API = "https://commons.wikimedia.org/w/api.php"
    params = {"action": "query", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
              "gsrnamespace": 6, "gsrlimit": want * 4, "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1600, "format": "json"}
    got = 0
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    API + "?" + urllib.parse.urlencode(params), headers=UA), timeout=30) as r:
                pages = json.load(r).get("query", {}).get("pages", {})
            break
        except Exception:
            time.sleep(2)
    else:
        return 0
    for p in sorted(pages.values(), key=lambda x: x.get("index", 99)):
        if got >= want:
            break
        infos = p.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        if info.get("width", 0) < min_w or info.get("width", 0) < info.get("height", 0):
            continue
        lic = (info.get("extmetadata", {}).get("LicenseShortName", {}) or {}).get("value", "")
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    info.get("thumburl") or info["url"], headers=UA), timeout=120) as r:
                data = r.read()
        except Exception:
            continue
        name = _save("images", slug, data, info.get("descriptionurl", ""), lic, summary, tags, anchor)
        if name:
            got += 1
        time.sleep(0.3)
    return got


def pexels_photos(slug, query, want, summary, tags, anchor, orientation="landscape"):
    import urllib.parse
    got = 0
    try:
        url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
            {"query": query, "per_page": want * 3, "orientation": orientation})
        with urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA, Authorization=PEXELS)), timeout=30) as r:
            photos = json.load(r).get("photos", [])
    except Exception:
        return 0
    for ph in photos:
        if got >= want:
            break
        src = ph.get("src", {}).get("large2x") or ph.get("src", {}).get("large")
        if not src:
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(src, headers=UA), timeout=120) as r:
                data = r.read()
        except Exception:
            continue
        name = _save("images", slug, data, ph.get("url", ""), "Pexels License", summary, tags, anchor)
        if name:
            got += 1
    return got


def pixabay_photos(slug, query, want, summary, tags, anchor):
    import urllib.parse
    got = 0
    try:
        url = "https://pixabay.com/api/?" + urllib.parse.urlencode(
            {"key": PIXABAY, "q": query, "per_page": max(3, want * 3), "image_type": "photo",
             "orientation": "horizontal", "safesearch": "true"})
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            hits = json.load(r).get("hits", [])
    except Exception:
        return 0
    for h in hits:
        if got >= want:
            break
        src = h.get("largeImageURL") or h.get("webformatURL")
        try:
            with urllib.request.urlopen(urllib.request.Request(src, headers=UA), timeout=120) as r:
                data = r.read()
        except Exception:
            continue
        name = _save("images", slug, data, h.get("pageURL", ""), "Pixabay License", summary, tags, anchor)
        if name:
            got += 1
    return got


def mixkit_videos(slug, category, want, summary, tags, anchor, trim=(6.0, 14.0)):
    """Mixkit 视频：抓分类页 -> 720p 直链 -> 裁剪为 8-10 秒。"""
    got = 0
    try:
        with urllib.request.urlopen(urllib.request.Request(
                f"https://mixkit.co/free-stock-video/{category}/", headers=UA), timeout=40) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception:
        return 0
    ids = list(dict.fromkeys(re.findall(r"assets\.mixkit\.co/videos/(\d+)/\d+-\d+\.mp4", html)))
    for vid in ids:
        if got >= want:
            break
        tmp = BUNDLE / f"_tmp_{vid}.mp4"
        ok = False
        for res in (720, 360):
            try:
                with urllib.request.urlopen(urllib.request.Request(
                        f"https://assets.mixkit.co/videos/{vid}/{vid}-{res}.mp4", headers=UA), timeout=240) as r:
                    data = r.read()
                if data[4:8] == b"ftyp" and len(data) > 200_000:
                    tmp.write_bytes(data)
                    ok = True
                    break
            except Exception:
                continue
        if not ok:
            continue
        n = _num()
        out = BUNDLE / "videos" / f"{n:02d}-{slug}.mp4"
        # 从 15% 处裁 10 秒
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "csv=p=0", str(tmp)], capture_output=True, text=True)
        try:
            dur = float(r.stdout.strip())
        except ValueError:
            tmp.unlink(missing_ok=True)
            continue
        start = min(max(1.0, dur * 0.15), max(1.0, dur - 6))
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", "10",
                            "-i", str(tmp), "-map", "0:v:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-preset", "veryfast", "-movflags", "+faststart", str(out)],
                           capture_output=True)
        tmp.unlink(missing_ok=True)
        if r.returncode == 0 and out.is_file() and out.stat().st_size > 50_000:
            meta.append({"file": f"videos/{out.name}", "source_url": f"https://mixkit.co/free-stock-video/{category}/",
                         "license": "Mixkit Stock Video Free License", "summary": summary,
                         "tags": tags, "script_anchor": anchor})
            got += 1
        else:
            out.unlink(missing_ok=True)
    return got


def pexels_videos(slug, query, want, summary, tags, anchor, max_sec=25):
    import urllib.parse
    got = 0
    try:
        url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
            {"query": query, "per_page": want * 3, "orientation": "landscape"})
        with urllib.request.urlopen(urllib.request.Request(url, headers=dict(UA, Authorization=PEXELS)), timeout=30) as r:
            vids = json.load(r).get("videos", [])
    except Exception:
        return 0
    for v in vids:
        if got >= want:
            break
        if v.get("duration", 99) > max_sec * 4:
            continue
        files = [f for f in v.get("video_files", []) if f.get("width") and 900 <= f["width"] <= 1500]
        f = min(files, key=lambda x: x["width"]) if files else None
        if not f:
            continue
        try:
            with urllib.request.urlopen(urllib.request.Request(f["link"], headers=UA), timeout=300) as r:
                data = r.read()
        except Exception:
            continue
        n = _num()
        tmp = BUNDLE / f"_tmp_px_{v['id']}.mp4"
        tmp.write_bytes(data)
        out = BUNDLE / "videos" / f"{n:02d}-{slug}.mp4"
        start = min(max(1.0, v.get("duration", 10) * 0.15), max(1.0, v.get("duration", 10) - 6))
        r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", "10",
                            "-i", str(tmp), "-map", "0:v:0", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                            "-preset", "veryfast", "-movflags", "+faststart", str(out)], capture_output=True)
        tmp.unlink(missing_ok=True)
        if r.returncode == 0 and out.is_file() and out.stat().st_size > 50_000:
            meta.append({"file": f"videos/{out.name}", "source_url": v.get("url", ""),
                         "license": "Pexels License", "summary": summary, "tags": tags,
                         "script_anchor": anchor})
            got += 1
        else:
            out.unlink(missing_ok=True)
    return got


def main():
    plan = json.loads((BUNDLE / '_plan.json').read_text(encoding='utf-8'))
    log = []
    for item in plan:
        kind = item["kind"]
        try:
            if kind == "commons":
                n = commons(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "pexels":
                n = pexels_photos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "pixabay":
                n = pixabay_photos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "mixkit":
                n = mixkit_videos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            elif kind == "pexelsv":
                n = pexels_videos(item["slug"], item["q"], item["want"], item["summary"], item["tags"], item["anchor"])
            else:
                n = 0
        except Exception as e:
            n = f"ERR {e}"[:60]
        log.append(f"{kind:8s} {item['slug']:16s} -> {n}")
        META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(log))
    print("total assets:", len(meta))


if __name__ == "__main__":
    main()
