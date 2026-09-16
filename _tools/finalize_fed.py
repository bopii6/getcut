#!/usr/bin/env python3
"""收尾：补 4 张 Pexels 图 → 删掉错图与垃圾候选 → 裁掉水印 → 按文案顺序重编号。"""
import io
import json
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

BUNDLE = Path(r"E:/短视频生成/美联储加息-素材包")
IMAGES = BUNDLE / "images"
META = Path(r"E:/短视频生成/_tools/_fed_meta.json")
PEXELS_KEY = Path(r"E:/短视频生成/videogen/pexels_key.txt").read_text(encoding="utf-8").strip()
UA = {"User-Agent": "NiwoBundleFetcher/1.0"}

EXTRA = [("wallstreet-sign", "wall street sign new york"),
         ("market-screen", "stock market data screen trading"),
         ("business-meeting", "business meeting office finance"),
         ("gas-night", "gas station night lights")]

# 被判定为错误的图（联络图核验）
DROP = {"15-fed-building-us.jpg", "16-fomc-room.jpg", "18-wallstreet.jpg",
        "19-trading-floor.jpg", "23-pboc.jpg", "26-fx-board.jpg", "27-inflation-chart.jpg"}

# 最终顺序（文案推进）→ 源文件
ORDER = [
    ("01-fed-building", "13-fed-building.jpg"),
    ("02-fed-building-2", "17-presser.jpg"),
    ("03-fed-rate-chart", "C:/Users/wang/AppData/Local/Temp/opencode/fred_rate.png"),
    ("04-usd-closeup", "01-usd-closeup.jpg"),
    ("05-mortgage-docs", "22-mortgage-doc.jpg"),
    ("06-bank-counter", "03-bank-interior.jpg"),
    ("07-coins", "12-coins.jpg"),
    ("08-calculator", "02-calculator.jpg"),
    ("09-cpi-chart", "C:/Users/wang/AppData/Local/Temp/opencode/fred_cpi.png"),
    ("10-supermarket", "08-groceries.jpg"),
    ("11-gas-pump", "20-gas-sign.jpg"),
    ("12-oil-well", "21-oil-refinery.jpg"),
    ("13-market-laptop", "07-laptop-chart.jpg"),
    ("14-car-dealer", "05-sale-car.jpg"),
    ("15-card-pay", "04-wallet-card.jpg"),
    ("16-factory", "06-factory-2.jpg"),
    ("17-fx-window", "11-fx.jpg"),
    ("18-yuan-100", "24-yuan.jpg"),
    ("19-yuan-notes", "25-yuan.jpg"),
    ("20-nyc-skyline", "10-skyline.jpg"),
]


def pexels(query):
    url = "https://api.pexels.com/v1/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": "landscape", "size": "large", "per_page": "5"})
    with urllib.request.urlopen(urllib.request.Request(
            url, headers={"Authorization": PEXELS_KEY, **UA}), timeout=45) as r:
        data = json.load(r)
    for p in data.get("photos", []):
        if (p.get("width") or 0) >= 1400:
            return p["src"].get("large2x") or p["src"]["large"], p.get("url", ""), p.get("alt", "")
    return None, None, None


def main():
    meta = json.loads(META.read_text(encoding="utf-8"))
    by_file = {i["file"].split("/")[-1]: i for i in meta["images"]}

    # 1) 补 Pexels 图
    for slug, q in EXTRA:
        u, page, alt = pexels(q)
        if not u:
            print("x extra", slug)
            continue
        dest = IMAGES / f"x-{slug}.jpg"
        with urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=90) as r:
            dest.write_bytes(r.read())
        im = Image.open(dest)
        by_file[dest.name] = {"url": u, "source_url": page, "title": alt, "w": im.size[0],
                              "h": im.size[1], "license": "Pexels License", "creator": "",
                              "provider": "pexels", "file": f"images/{dest.name}",
                              "bytes": dest.stat().st_size, "via": "pexels-extra"}
        print("EXTRA", dest.name, im.size)

    # 2) 删除错图与所有候选垃圾
    removed = 0
    for f in list(IMAGES.glob("*.jpg")) + list(IMAGES.glob("*.png")):
        if f.name in DROP or f.name.startswith("c1"):
            f.unlink()
            removed += 1
    print("removed", removed)

    # 3) 裁水印（14-fed-building 右上角"新华社"）
    src14 = IMAGES / "14-fed-building.jpg"
    if src14.exists():
        im = Image.open(src14)
        w, h = im.size
        im.crop((0, int(h * 0.13), w, h)).save(IMAGES / "14-fed-building.jpg", "JPEG", quality=92)
        print("cropped watermark on 14")

    # 4) 按顺序重命名
    final = []
    for new, old in ORDER:
        src = Path(old) if "/" in old or ":" in old else IMAGES / old
        if not src.exists():
            print("MISSING", old)
            continue
        ext = ".png" if src.suffix.lower() == ".png" else ".jpg"
        dst = IMAGES / f"{new}{ext}"
        im = Image.open(src)
        if ext == ".jpg":
            im.convert("RGB").save(dst, "JPEG", quality=92)
        else:
            shutil.copy(src, dst)
        if src.parent == IMAGES and src.name != dst.name:
            src.unlink()
        info = by_file.get(Path(old).name, {"provider": "fred", "source_url":
                                            "https://fred.stlouisfed.org/", "title": "FRED chart",
                                            "license": "Public Domain (FRED)"})
        final.append(dict(info, file=f"images/{dst.name}", w=im.size[0], h=im.size[1],
                          bytes=dst.stat().st_size))
        print("FINAL", dst.name, im.size)

    meta["images"] = final
    META.write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("images:", len(final))


if __name__ == "__main__":
    main()
