#!/usr/bin/env python3
"""第二轮补图：英文精准查询，每个主题抓多个候选（文件名带 a/b/c 后缀），稍后人工筛选。"""
import io
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BUNDLE = Path(r"E:/短视频生成/美联储加息-素材包")
IMAGES = BUNDLE / "images"
META = Path(r"E:/短视频生成/_tools/_fed_meta.json")
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
SKIP = ("upload.wikimedia.org", "commons.wikimedia.org", "gettyimages", "shutterstock",
        "istockphoto", "alamy", "dreamstime", "123rf", "depositphotos", "vcg.com")

PLAN = [
    ("powell", '"Jerome Powell" Federal Reserve chair speech podium', 4),
    ("warsh", '"Kevin Warsh" Federal Reserve chair', 4),
    ("fomc-room", 'Federal Reserve Board meeting room table Washington', 4),
    ("nyse", 'New York Stock Exchange building facade Wall Street', 4),
    ("trading", 'stock exchange trading floor traders screens', 4),
    ("bank-hq", 'large bank headquarters building glass tower', 4),
    ("inflation", 'US inflation rate chart CPI graph', 4),
    ("fed-rate", 'federal funds rate chart historical', 4),
    ("pboc", "People's Bank of China headquarters building Beijing", 4),
    ("gas-price", 'gas station price sign dollar per gallon', 4),
]


def bing(query, want=8):
    url = "https://www.bing.com/images/search?" + urllib.parse.urlencode(
        {"q": query, "form": "HDRSC2", "first": "1", "count": "40"})
    try:
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}), timeout=30) as r:
            html = r.read().decode("utf-8", "ignore")
    except Exception as e:
        print("   bing err:", str(e)[:60])
        return []
    out = []
    for m in re.finditer(r'm="(\{[^"]+?\})"', html):
        try:
            o = json.loads(m.group(1).replace("&quot;", '"'))
        except Exception:
            continue
        u, p = o.get("murl"), o.get("purl")
        if not u or not p or any(h in u for h in SKIP):
            continue
        out.append({"url": u, "source_url": p, "title": (o.get("t") or "")[:80]})
        if len(out) >= want:
            break
    return out


def grab(url, dest, referer="https://www.bing.com/"):
    with urllib.request.urlopen(urllib.request.Request(url, headers={
            "User-Agent": UA, "Referer": referer, "Accept": "image/*,*/*;q=0.8"}), timeout=45) as r:
        data = r.read()
    if len(data) < 50000:
        raise ValueError("small")
    im = Image.open(io.BytesIO(data))
    if min(im.size) < 600 or im.size[0] <= im.size[1]:
        raise ValueError(f"size {im.size}")
    im.convert("RGB").save(dest, "JPEG", quality=92)
    return im.size


def main():
    meta = json.loads(META.read_text(encoding="utf-8"))
    n = 100                      # 候选从 100 起编号，便于稍后区分
    for slug, query, want in PLAN:
        got = 0
        for cand in bing(query, want + 8):
            if got >= want:
                break
            n += 1
            dest = IMAGES / f"c{n}-{slug}.jpg"
            try:
                size = grab(cand["url"], dest)
            except Exception as e:
                n -= 1
                continue
            meta["images"].append({
                "url": cand["url"], "source_url": cand["source_url"], "title": cand["title"],
                "w": size[0], "h": size[1], "license": "", "creator": "",
                "provider": "bing", "file": f"images/{dest.name}",
                "bytes": dest.stat().st_size, "via": "bing2"})
            got += 1
            print("CAND", dest.name, size, cand["title"][:40], flush=True)
            time.sleep(0.15)
        print("  ->", slug, got, "candidates")
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("total entries:", len(meta["images"]))


if __name__ == "__main__":
    main()
