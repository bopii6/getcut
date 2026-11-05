# -*- coding: utf-8 -*-
import os, json, shutil

DEST = r"E:\getcut\ref\originals"
items = json.load(open(os.path.join(DEST, "index.json"), encoding="utf-8"))

ren = {}
rows = []
xs = sorted([i for i in items if i["name"].startswith("x_")], key=lambda i: i["name"])
for i, it in enumerate(xs):
    new = f"yas_{i+1:02d}_{int(it['dur'])}s_{it['w']}x{it['h']}.mp4"
    if it["name"] != new and os.path.exists(os.path.join(DEST, it["name"])):
        os.rename(os.path.join(DEST, it["name"]), os.path.join(DEST, new))
    it["name"] = new
    rows.append(it)

vg = [i for i in items if i["name"].startswith("vg_")]
for it in vg:
    rows.append(it)

json.dump(rows, open(os.path.join(DEST, "index.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=2)

lines = ["# 原片清单", "",
         "## A. Yas 本人的原片（x.com/bizdevelo，2024 年）", "",
         "| # | 文件 | 时长 | 分辨率 |", "|---|---|---|---|"]
for i, it in enumerate(xs, 1):
    lines.append(f"| {i} | `{it['name']}` | {it['dur']}s | {it['w']}×{it['h']} |")
lines += ["", "## B. vidguy 官方样片（他们这套系统的产出）", "",
          "| 文件 | 时长 | 分辨率 | 说明 |", "|---|---|---|---|"]
notes = {
    "bobby": "3D 卡通角色 Bobby，渲染级人物（我们要补的就是这一层）",
    "keira-morph": "真人→AI 网红换脸对比",
    "swap_original": "原始素材",
    "swap_keira": "换脸后",
    "clip-01": "Keira 竖屏片段",
    "clip-02": "Keira 竖屏片段",
    "clip-03": "Keira 竖屏片段",
}
for it in vg:
    d = next((v for k, v in notes.items() if k.split("_")[-1] in it["name"] or k in it["name"]), "")
    lines.append(f"| `{it['name']}` | {it['dur']}s | {it['w']}×{it['h']} | {d} |")

lines += ["", "---", "",
          "**说明**：他 2026 年那套卡通短视频发在 TikTok/IG，X 上没有可下载的原始文件",
          "（需要账号名 + 登录态），所以这里拿不到。上面 A 组是他真人时期的原片，",
          "B 组是同一套生产系统的卡通产出。"]
open(os.path.join(DEST, "index.md"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines[:12]))
print("... total", len(rows))
