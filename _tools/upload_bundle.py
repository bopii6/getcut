#!/usr/bin/env python3
"""Upload the niwo bundle to niwo.studio via its presigned-URL API.

Mirrors the frontend flow: find/create project -> presign each asset ->
PUT bytes to S3 -> submit content+manifest via /bundle.
"""
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

API = "https://niwo.studio/api/v1"
BUNDLE = Path(r"E:/短视频生成/niwo-bundle-ai-pause")
TOKEN = Path(r"E:/短视频生成/_tools/_niwo_token.txt").read_text(encoding="utf-8").strip()

s = requests.Session()
s.headers.update({"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})

CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".webp": "image/webp", ".gif": "image/gif",
    ".mp4": "video/mp4", ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".webm": "video/webm",
}


def api_get(path, **kw):
    r = s.get(API + path, timeout=30, **kw)
    r.raise_for_status()
    return r.json()


def api_post(path, body=None, **kw):
    r = s.post(API + path, json=body if body is not None else {}, timeout=60, **kw)
    r.raise_for_status()
    return r.json()


def api_put_json(path, body):
    r = s.put(API + path, json=body, timeout=120)
    r.raise_for_status()
    return r.json()


def collect_assets():
    assets = []
    for sub in ("images", "videos"):
        for p in sorted((BUNDLE / sub).iterdir()):
            if p.is_file() and not p.name.startswith("."):
                assets.append(p)
    return assets


def upload_one(item: dict, file: Path):
    ct = item["content_type"]
    with open(file, "rb") as fh:
        r = requests.put(item["upload_url"], data=fh.read(),
                         headers={"Content-Type": ct}, timeout=300)
    r.raise_for_status()
    return item["path"], r.status_code


def main():
    content = json.loads((BUNDLE / "content.json").read_text(encoding="utf-8"))
    manifest = json.loads((BUNDLE / "manifest.json").read_text(encoding="utf-8"))
    assets = collect_assets()
    print(f"assets to upload: {len(assets)}")

    # 1. reuse the empty project the page just created, else make one
    projects = api_get("/video-studio/projects").get("data", {}).get("items", [])
    target = None
    for p in projects:
        if not p.get("is_demo") and p.get("asset_count") == 0:
            target = p
            break
    if target:
        pid = target["project_id"] or target["id"]
        print("reusing empty project:", pid)
    else:
        pid = api_post("/video-studio/projects")["data"]["project_id"]
        print("created project:", pid)

    # 2. presign
    files = [{"path": f"images/{p.name}" if p.parent.name == "images" else f"videos/{p.name}",
              "size_bytes": p.stat().st_size} for p in assets]
    sign = api_post(f"/video-studio/projects/{pid}/upload-urls", {"files": files})["data"]
    items = sign["items"]
    print(f"presigned: {len(items)} urls")

    # 3. upload bytes
    by_path = {f"images/{p.name}" if p.parent.name == "images" else f"videos/{p.name}": p
               for p in assets}
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda it: upload_one(it, by_path[it["path"]]), items))
    ok = sum(1 for _, code in results if code in (200, 201))
    print(f"uploaded: {ok}/{len(results)}")

    # 4. submit bundle
    cover = next((f"images/{p.name}" for p in assets if p.parent.name == "images"), None)
    resp = api_put_json(f"/video-studio/projects/{pid}/bundle",
                        {"content": content, "manifest": manifest, "cover_path": cover})
    print("bundle submit:", json.dumps(resp, ensure_ascii=False)[:400])

    # 5. verify
    proj = api_get(f"/video-studio/projects/{pid}")["data"]
    print("project now:", json.dumps({k: proj.get(k) for k in
          ("project_id", "title", "asset_count", "status", "updated_at")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
