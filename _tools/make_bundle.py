#!/usr/bin/env python3
"""Generate content.json and manifest.json for the AI-pause bundle."""
import json
from pathlib import Path

BUNDLE = Path(r"E:/短视频生成/niwo-bundle-ai-pause")
META = Path(r"E:/短视频生成/_tools/_assets_meta.json")

script = (BUNDLE / "_script.txt").read_text(encoding="utf-8").strip()

content = {
    "schema_version": 1,
    "title": "AI放缓之争：Anthropic喊停，白宫说不",
    "script": script,
    "hook_headline": {
        "lines": ["造AI的人主动喊停", "白宫：[[一步都不能慢]]"]
    },
    "sources": ["Anthropic 官方博客", "纽约时报", "CNBC", "路透社", "华尔街日报", "环球时报"],
    "pronunciations": {"长文": "chang2 wen2"},
    "notes": "素材按横构图收集，建议在 Niwo 里选竖屏信息版渲染。视频素材来自 Mixkit（Mixkit Stock Video Free License），图片来自 Wikimedia Commons（CC 或公有领域，来源页与授权见 manifest）。文案中的事实均引用 sources 所列公开报道，成片如需免责声明请在渲染参数里自行开启。",
}

meta = {m["file"]: m for m in json.loads(META.read_text(encoding="utf-8"))}

MIXKIT_PAGE = {
    "01-datacenter.mp4": "https://mixkit.co/free-stock-video/data-center/",
    "03-tech.mp4": "https://mixkit.co/free-stock-video/technology/",
    "05-city.mp4": "https://mixkit.co/free-stock-video/city-night/",
    "06-finance.mp4": "https://mixkit.co/free-stock-video/finance-and-money/",
    "07-finance.mp4": "https://mixkit.co/free-stock-video/finance-and-money/",
    "08-robot.mp4": "https://mixkit.co/free-stock-video/robot/",
    "09-robot.mp4": "https://mixkit.co/free-stock-video/robot/",
    "10-crowd.mp4": "https://mixkit.co/free-stock-video/crowd/",
    "11-office.mp4": "https://mixkit.co/free-stock-video/office/",
    "14-server.mp4": "https://mixkit.co/free-stock-video/server/",
}
MIXKIT_LIC = "Mixkit Stock Video Free License"

# (file, summary, tags, anchor) in script progression order
ENTRIES = [
    ("images/01-amodei.jpg", "Anthropic CEO达里奥·阿莫迪在科技大会上发言特写",
     ["阿莫迪", "Anthropic", "CEO"], "造AI的人，自己喊停了"),
    ("images/34-brake.jpg", "黑底上的金属刹车盘特写",
     ["刹车盘", "特写", "减速"], "我们必须给前沿AI踩刹车"),
    ("images/03-amodei.jpg", "阿莫迪坐在大会舞台上与主持人对谈",
     ["阿莫迪", "论坛", "访谈"], "各家别再比赛式地提升模型能力了"),
    ("images/10-datacenter.jpg", "数据中心机房内整齐排布的服务器机柜",
     ["数据中心", "服务器", "机房"], "各家别再比赛式地提升模型能力了"),
    ("images/11-datacenter.jpg", "大型数据中心建筑外观与冷却机组",
     ["数据中心", "算力", "建筑"], "各家别再比赛式地提升模型能力了"),
    ("videos/01-datacenter.mp4", "机房里成排服务器机柜，蓝色灯带向前延伸",
     ["机房", "服务器", "科技"], "各家别再比赛式地提升模型能力了"),
    ("videos/09-robot.mp4", "白色人形机器人正对镜头摆动手臂",
     ["人形机器人", "人工智能"], "失控的AI智能体，最坏六个月就能接管整个互联网"),
    ("images/27-robot.jpg", "工程师与人形机器人在实验室里协作",
     ["机器人", "实验室", "工程师"], "是他们自己做出来的东西，自己先怕了"),
    ("videos/14-server.mp4", "工作人员在昏暗机房里检修服务器机柜",
     ["机房", "运维", "服务器"], "是他们自己做出来的东西，自己先怕了"),
    ("videos/03-tech.mp4", "眼镜片特写反射出滚动的代码屏幕",
     ["代码", "程序员", "特写"], "政府的监管根本追不上AI的速度"),
    ("images/32-trump.jpg", "特朗普在椭圆形办公室俯身签署行政令",
     ["特朗普", "白宫", "签署"], "可白宫第一反应就是不行"),
    ("images/33-trump.jpg", "特朗普坐在办公桌前签署文件，幕僚站在身后",
     ["特朗普", "签署", "椭圆办公室"], "可白宫第一反应就是不行"),
    ("images/08-whitehouse.jpg", "白宫北草坪与主楼外景，白天",
     ["白宫", "华盛顿", "美国政府"], "可白宫第一反应就是不行"),
    ("images/21-washington.jpg", "美国国会大厦黄昏外景",
     ["国会", "华盛顿", "美国"], "放缓就是给中国让路"),
    ("images/05-trump.jpg", "写着TRUMP的竞选讲台，台下人群举着手机",
     ["特朗普", "讲台", "集会"], "美国必须跑赢，一步都不能慢"),
    ("images/13-gpu.jpg", "一块华硕英伟达GeForce显卡横放特写",
     ["显卡", "GPU", "芯片"], "建议政府直接对华禁售高端AI芯片"),
    ("images/15-chip.jpg", "电路板与芯片元器件微距特写",
     ["芯片", "电路板", "微距"], "建议政府直接对华禁售高端AI芯片"),
    ("videos/06-finance.mp4", "大量美元钞票堆叠铺满画面",
     ["美元", "钞票", "金钱"], "阿莫迪还顺势加码"),
    ("images/19-beijing.jpg", "北京望京CBD高楼天际线",
     ["北京", "天际线", "中国"], "中国这边第二天就回击了"),
    ("images/20-beijing.jpg", "北京建外SOHO与央视总部大楼",
     ["北京", "CBD", "地标"], "环球时报发社评"),
    ("videos/07-finance.mp4", "一个人坐在桌前清点美元现金",
     ["数钱", "现金", "美元"], "华尔街日报还透露"),
    ("images/25-stocks.jpg", "法兰克福证券交易所交易大厅与屏幕墙",
     ["交易所", "股市", "金融"], "几家AI大公司私下其实都同意该慢一点"),
    ("images/26-stocks.jpg", "证交所内悬挂的指数显示屏",
     ["交易所", "行情", "屏幕"], "只是没谁敢第一个停"),
    ("images/28-un.jpg", "联合国大会会议厅的绿色大理石讲台",
     ["联合国", "国际会议"], "中美准备在9月中旬开第一场专门谈AI安全的高层对话"),
    ("images/09-whitehouse.jpg", "白宫主楼正面，草坪与喷泉",
     ["白宫", "建筑", "美国"], "九月中旬这场对话，建议你盯紧点"),
    ("videos/05-city.mp4", "城市高楼夜景航拍，道路车流灯光穿梭",
     ["城市", "夜景", "航拍"], "九月中旬这场对话，建议你盯紧点"),
    ("images/31-steering.jpg", "红色野马老爷车车窗内的方向盘特写",
     ["方向盘", "汽车", "驾驶"], "两个大国在抢方向盘"),
    ("videos/11-office.mp4", "开放式办公室里员工们在工位用电脑办公",
     ["办公室", "职场", "工位"], "AI是以靠谱的方式走进你的工作"),
    ("videos/08-robot.mp4", "工厂车间里的白色机械臂在自动作业",
     ["机械臂", "工厂", "自动化"], "AI是以靠谱的方式走进你的工作"),
    ("videos/10-crowd.mp4", "繁忙路口大量行人正在过马路",
     ["人群", "街道", "通勤"], "还是先在你的行业里掀了桌子"),
    ("images/35-hearing.jpg", "参议院听证会大厅里坐满听众",
     ["听证会", "国会", "会议"], "可能比任何一次新模型发布都重要"),
]

assets = []
for fname, summary, tags, anchor in ENTRIES:
    assert anchor in script, f"anchor not in script: {anchor!r}"
    entry = {
        "file": fname,
        "kind": "video" if fname.endswith(".mp4") else "image",
        "summary": summary,
        "tags": tags,
        "script_anchor": anchor,
    }
    if fname.startswith("videos/"):
        entry["source_url"] = MIXKIT_PAGE[Path(fname).name]
        entry["license"] = MIXKIT_LIC
    else:
        m = meta[fname]
        entry["source_url"] = m["page"]
        if m.get("license"):
            entry["license"] = m["license"]
    assets.append(entry)

manifest = {
    "schema_version": 1,
    "generated_by": "zcode (GLM) with niwo-render-everything 1.0.0",
    "notes": "竖屏信息版取向：视频均为横构图 720p、已裁成 5-10 秒短镜头（无需再标选段）；图片多为横构图。manifest 顺序跟随口播文案推进。",
    "assets": assets,
}

(BUNDLE / "content.json").write_text(
    json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
(BUNDLE / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print("content.json + manifest.json written,", len(assets), "assets")
