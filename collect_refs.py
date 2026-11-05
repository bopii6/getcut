# -*- coding: utf-8 -*-
import os, shutil

SRC = r"E:\getcut\ref\format"
DST = r"E:\getcut\ref\参考片"
MAP = {
    "vg_ai-fruit-story.mp4":        ("A_3D动画短剧", "01_水果恋_3D动画.mp4", "两条水果拟人谈恋爱，15 秒，3 个镜头各 5 秒"),
    "vg_v01.mp4":                   ("A_3D动画短剧", "02_老爷爷读书_3D动画.mp4", "3D 老爷爷给小孩读书，20 秒，最接近他说的 cast 风格"),
    "vg_grandmas-cookie-drop.mp4":  ("C_角色一致性", "03_猫咪播客_同一角色.mp4", "猫主播，同一角色多场景"),
    "vg_hailuo-premium-duo.mp4":    ("C_角色一致性", "04_双人播客_数字人.mp4", "真人级数字人播客，15 秒"),
    "vg_moisturizer-ugc.mp4":       ("B_UGC真人感", "05_护肤UGC.mp4", "手持自拍 UGC，15 秒"),
    "vg_unboxing-ugc.mp4":          ("B_UGC真人感", "06_开箱UGC.mp4", "开箱，15 秒"),
    "vg_tennis-ai-edit.mp4":        ("B_UGC真人感", "07_网球剪辑_字幕.mp4", "AI 剪辑 + 关键词字幕，8 秒"),
    "vg_sizzle-food-macro.mp4":     ("B_UGC真人感", "08_美食空镜_素材.mp4", "4 秒空镜，就是文章里说的 ai 片段"),
    "vg_companion-loop.mp4":        ("D_工具界面", "09_产品界面.mp4", "他们家 App 的对话界面录屏"),
}
for f, (sub, new, note) in MAP.items():
    s = os.path.join(SRC, f)
    if not os.path.exists(s):
        print("MISS", f); continue
    d = os.path.join(DST, sub)
    os.makedirs(d, exist_ok=True)
    shutil.copy2(s, os.path.join(d, new))
    print("ok", sub, new)

# character clips
CH = r"E:\getcut\ref\originals"
CHMAP = {
    "vg_influencers_bobby-mechanic-reel.mp4": "10_卡通角色Bobby_3D.mp4",
    "vg_ai-influencers_keira-morph.mp4": "11_换脸对比_前后.mp4",
    "vg_keira_clip-01.mp4": "12_Keira片段01.mp4",
    "vg_keira_clip-02.mp4": "13_Keira片段02.mp4",
    "vg_keira_clip-03.mp4": "14_Keira片段03.mp4",
}
for f, new in CHMAP.items():
    s = os.path.join(CH, f)
    if not os.path.exists(s):
        print("MISS", f); continue
    d = os.path.join(DST, "D_工具界面")
    shutil.copy2(s, os.path.join(d, new))
    print("ok", new)

lines = ["# 参考片清单", "",
         "来源：vidguy.ai 官方素材（他做这套视频所用的同一套生产系统）", "",
         "| 分组 | 文件 | 说明 |", "|---|---|---|"]
for f, (sub, new, note) in MAP.items():
    lines.append(f"| {sub} | `{new}` | {note} |")
for f, new in CHMAP.items():
    lines.append(f"| 角色 | `{new}` | vidguy 角色资产 |")
lines += ["", "**注意**：他本人 TikTok 账号上的原片抓不到（需要登录+账号名），",
          "这里是他所用产品方的官方成片，格式、画风、生产方式与他那套一致。"]
open(os.path.join(DST, "index.md"), "w", encoding="utf-8").write("\n".join(lines))
print("index ok")
