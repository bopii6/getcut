#!/usr/bin/env python3
"""生成 content.json 与 manifest.json，跑 skill 自校验，然后打包 zip。"""
import io
import json
import subprocess
import zipfile
from pathlib import Path

BUNDLE = Path(r"E:/短视频生成/美联储加息-素材包")
META = Path(r"E:/短视频生成/_tools/_fed_meta.json")
SKILL = Path(r"C:/Users/wang/.agents/skills/niwo-render-everything")

SCRIPT = (
    "如果这两天你刷到美联储要加息的消息，可能会觉得跟自己没什么关系。但美国的一个利率决定，"
    "会一路传到你的房贷月供、你的存款利息，还有你去银行换外汇的牌价上。这条视频用三分钟把加息讲清楚："
    "加的是什么，为什么要加，以及它跟你有什么关系。"
    "先说清楚，美联储加息，加的不是你房贷的利率，而是一个叫联邦基金利率的东西。"
    "它是美国银行之间互相借隔夜资金的利率，也是整个金融体系里最短端、最基础的那个价格。"
    "你可以把它想成水位，水位一变，所有漂在上面的船都会动。"
    "目前这个利率的目标区间是百分之三点五到三点七五，从今年一月开始已经连续五次会议按兵不动。"
    "而这次如果真的动手，将是二零二三年以来的第一次加息，也是美联储主席沃什上任之后第一次加息。"
    "原因在于通胀没降到位。美国八月的数据显示，物价同比上涨百分之三点四，"
    "剔除食品和能源的核心通胀是百分之二点四，都还在美联储百分之二的目标之上。"
    "更麻烦的是能源在推着涨，国际油价已经站上一百美元一桶，汽油价格同比涨了百分之二十七。"
    "美联储主席沃什在八月的会议上说，必须确信通胀正明确、足够快地朝目标靠近，否则我们还有工作要做。"
    "这句话被市场解读为，加息的窗口打开了。本周数据公布之后，"
    "市场对这次加息二十五个基点的预期，从七成升到了九成左右。二十五个基点，就是零点二五个百分点。"
    "它怎么传到普通人身上？链条是这样：美联储把银行之间借钱的成本抬上去，银行的资金成本上升，"
    "房贷、车贷、信用卡和企业的贷款利率跟着抬；同时存款和货币基金的收益率也会变高。"
    "另一条线是汇率，美国利率高了，全球资金更愿意换成美元去赚利差，美元走强，其他货币就承压。"
    "对股市来说，无风险的利率变高，未来才赚到的钱折回今天就更便宜，估值会被压一压。"
    "这就是为什么美联储一动，全球市场都跟着抖一下。"
    "那为什么会影响到中国？因为汇率和资本流动是连着的。美元利率高、美元强，人民币就有贬值压力。"
    "这时候中国央行面对一个两难：跟着收紧，会压到本来就需要支持的经济；不跟，就得靠别的工具稳住汇率和跨境资金。"
    "所以你看到的美联储决定，往往不只是美国的事，它会挤到别人的政策空间。"
    "最后说句冷静的。加息不是谁在针对谁，它只是美联储压自己通胀的工具，代价会外溢出去，"
    "而且它也不是立刻见效，通常要几个月才能压到物价上。对你个人来说，值得关注的是三件事："
    "如果你的房贷是浮动利率，看看重定价的日期；别因为美元利率高就去追高美元资产，汇率波动可能吃掉利差；"
    "这次决议就在周四凌晨，重点不只是加不加，还有会后公布的点阵图，"
    "它决定了这只是一次性调整，还是一轮连续加息的开始。"
)

CONTENT = {
    "schema_version": 1,
    "title": "美联储加息是什么意思：一条利率决定怎么传到你身上",
    "script": SCRIPT,
    "hook_headline": {"lines": ["美国要加息了", "你的[[房贷]]为什么跟着动"]},
    "sources": ["美国劳工统计局 8 月 CPI 报告", "美联储 FOMC 声明", "路透社", "纽约时报",
                "CNBC", "CME FedWatch", "圣路易斯联储 FRED"],
    "pronunciations": {"沃什": "wo4 shi2", "重定价": "chong2 ding4 jia4"},
    "notes": ("素材按横构图收集，建议在渲染界面选竖屏信息版。"
              "覆盖：美联储大楼、官方利率与通胀走势图（FRED）、美元现钞、房贷文件、银行换汇、"
              "超市物价、加油站与油田、行情屏、车行、刷卡、工厂、人民币与纽约街景。"
              "唯一缺项：美联储主席的人物照片（公开可用的高清授权照没找到），"
              "相关段落靠美联储大楼与行情画面承接。视频都已裁成 10 秒内的短镜头。"),
}

# file → (summary, tags, script_anchor)
ASSETS = {
    "images/01-fed-building.jpg": ("华盛顿美联储大楼正面外景，白色石墙与柱廊，晴天",
                                   ["美联储大楼", "华盛顿", "建筑", "外景"],
                                   "如果这两天你刷到美联储要加息的消息"),
    "images/02-fed-building-2.jpg": ("美联储大楼另一角度侧拍，建筑主体占据画面中部",
                                     ["美联储大楼", "机构", "建筑", "侧拍"],
                                     "将是二零二三年以来的第一次加息"),
    "images/03-fed-rate-chart.png": ("联邦基金利率历史走势折线图，带零轴与年刻度",
                                     ["利率走势", "联邦基金利率", "图表", "数据"],
                                     "目前这个利率的目标区间是百分之三点五到三点七五"),
    "images/14-fed-building.jpg": ("美联储大楼正面外景，蓝天、旗杆与石砌柱廊（已裁掉水印）",
                                   ["美联储大楼", "外景", "建筑", "国旗"],
                                   "它是美国银行之间互相借隔夜资金的利率"),
    "images/09-fuel.jpg": ("手握着绿色加油枪正在给车加油的近景",
                           ["加油枪", "加油", "手部", "能源"],
                           "汽油价格同比涨了百分之二十七"),
    "images/04-usd-closeup.jpg": ("多张一百美元纸币叠放的近景，可看到钞票纹理与面额",
                                  ["美元", "钞票", "近景", "货币"],
                                  "全球资金更愿意换成美元去赚利差"),
    "images/05-mortgage-docs.jpg": ("房屋贷款合同文件与一串钥匙放在桌面上",
                                    ["房贷", "合同", "钥匙", "文件"],
                                    "会一路传到你的房贷月供"),
    "images/06-bank-counter.jpg": ("银行换汇柜台窗口，玻璃后是外币牌价与柜员",
                                   ["银行", "换汇", "柜台", "外币"],
                                   "还有你去银行换外汇的牌价上"),
    "images/07-coins.jpg": ("硬币成堆散落在白色桌面，浅景深",
                            ["硬币", "存款", "零钱", "桌面"],
                            "你的存款利息"),
    "images/08-calculator.jpg": ("桌面上的计算器与财务图表，旁边有笔和纸张",
                                 ["计算器", "财务", "办公桌", "图表"],
                                 "二十五个基点，就是零点二五个百分点"),
    "images/09-cpi-chart.png": ("美国消费者物价指数同比走势折线图，曲线持续上行",
                                ["通胀走势", "CPI", "图表", "数据"],
                                "物价同比上涨百分之三点四"),
    "images/10-supermarket.jpg": ("超市里推着购物车挑选蔬果的顾客，货架整齐",
                                  ["超市", "购物", "货架", "物价"],
                                  "美国八月的数据显示"),
    "images/11-gas-pump.jpg": ("海边两座老旧加油泵，黄色机身，背景是海与天空",
                               ["加油泵", "能源", "户外", "海边"],
                               "汽油价格同比涨了百分之二十七"),
    "images/12-oil-well.jpg": ("黄昏下的抽油机剪影，背景有风机与落日",
                               ["抽油机", "油田", "日落", "能源"],
                               "国际油价已经站上一百美元一桶"),
    "images/13-market-laptop.jpg": ("办公桌上两台笔记本电脑显示股市行情图表",
                                    ["笔记本", "行情", "办公桌", "数据分析"],
                                    "对股市来说，无风险的利率变高"),
    "images/14-car-dealer.jpg": ("车行停车场内一排排新车整齐排开",
                                 ["车行", "汽车", "停车场", "销售"],
                                 "房贷、车贷、信用卡和企业的贷款利率跟着抬"),
    "images/15-card-pay.jpg": ("手持信用卡在手机上完成支付的特写",
                               ["信用卡", "支付", "手机", "特写"],
                               "房贷、车贷、信用卡和企业的贷款利率跟着抬"),
    "images/16-factory.jpg": ("老旧工厂车间里的成排机床设备",
                              ["工厂", "机床", "车间", "工业"],
                              "企业的贷款利率跟着抬"),
    "images/18-yuan-100.jpg": ("一百元人民币纸币正面，印有人民大会堂图案",
                               ["人民币", "百元", "纸币", "钞票"],
                               "人民币就有贬值压力"),
    "images/19-yuan-notes.jpg": ("多张不同面额人民币纸币并排摆放",
                                 ["人民币", "面额", "纸币", "钞票"],
                                 "人民币就有贬值压力"),
    "images/20-nyc-skyline.jpg": ("纽约曼哈顿天际线黄昏剪影，高楼群与落日",
                                  ["纽约", "天际线", "黄昏", "城市"],
                                  "最后说句冷静的"),
    "images/21-wallstreet-sign.jpg": ("纽约华尔街路口的街牌与红绿灯，背景是高楼",
                                      ["华尔街", "路牌", "纽约", "街景"],
                                      "对股市来说，无风险的利率变高"),
    "images/22-market-screen.jpg": ("电子屏上的行情界面，红绿K线与成交数据",
                                    ["行情屏", "K线", "交易", "屏幕"],
                                    "估值会被压一压"),
    "images/23-gas-night.jpg": ("夜晚的加油站，灯光明亮，一辆车正在驶入",
                                ["加油站", "夜景", "汽车", "灯光"],
                                "国际油价已经站上一百美元一桶"),
    "images/24-business-meeting.jpg": ("会议室里几个人围着铺满图表的桌面讨论",
                                       ["会议", "数据分析", "讨论", "办公"],
                                       "银行的资金成本上升"),
    "videos/01-wallstreet.mp4": ("纽约华尔街街景，两侧高楼与来往行人车辆",
                                 ["华尔街", "街道", "建筑", "纽约"],
                                 "对股市来说，无风险的利率变高"),
    "videos/02-money.mp4": ("点钞机清点美元纸币的特写",
                            ["点钞", "美元", "现金", "特写"],
                            "同时存款和货币基金的收益率也会变高"),
    "videos/03-gas.mp4": ("加油枪插入汽车油箱加油，手部动作特写",
                          ["加油", "汽车", "加油站", "手部"],
                          "汽油价格同比涨了百分之二十七"),
    "videos/04-market.mp4": ("屏幕上滚动的行情图表与交易数据",
                             ["行情屏", "图表", "交易", "屏幕"],
                             "估值会被压一压"),
    "videos/05-supermarket.mp4": ("超市里推购物车采购的顾客与货架",
                                  ["超市", "购物", "货架", "人群"],
                                  "物价同比上涨百分之三点四"),
    "videos/06-bank.mp4": ("城市中的银行建筑与街景",
                           ["银行", "建筑", "城市", "金融"],
                           "银行的资金成本上升"),
    "videos/07-laptop.mp4": ("办公桌上的笔记本电脑显示行情图表，手在键盘上操作",
                             ["笔记本", "图表", "办公", "手部"],
                             "无风险的利率变高"),
    "videos/08-skyline.mp4": ("纽约城市天际线航拍移动镜头",
                              ["天际线", "航拍", "城市", "建筑"],
                              "美元走强"),
    "videos/09-card.mp4": ("刷卡支付动作特写，POS 机与信用卡",
                           ["刷卡", "支付", "收银", "特写"],
                           "信用卡和企业的贷款利率跟着抬"),
    "videos/10-factory.mp4": ("工厂车间内机器运转与流水线作业",
                              ["工厂", "机械", "流水线", "工业"],
                              "企业的贷款利率跟着抬"),
    "videos/11-traffic.mp4": ("夜间城市车流延时，车灯拉出光带",
                              ["车流", "夜景", "城市", "延时"],
                              "最后说句冷静的"),
    "videos/12-oil.mp4": ("白天油田上的抽油机持续运转",
                          ["抽油机", "油田", "能源", "运转"],
                          "国际油价已经站上一百美元一桶"),
}


def main():
    dup = BUNDLE / "images" / "17-fx-window.jpg"
    if dup.exists():
        dup.unlink()
        print("dropped duplicate 17-fx-window.jpg")
    meta = json.loads(META.read_text(encoding="utf-8"))
    src = {i["file"].split("/")[-1]: i for i in meta["images"]}
    src.update({v["file"].split("/")[-1]: v for v in meta["videos"]})

    assets = []
    for f, (summary, tags, anchor) in ASSETS.items():
        p = BUNDLE / f
        if not p.exists():
            print("MISSING", f)
            continue
        info = src.get(p.name, {})
        item = {"file": f, "kind": "video" if f.startswith("videos/") else "image",
                "summary": summary, "tags": tags, "script_anchor": anchor}
        if info.get("source_url"):
            item["source_url"] = info["source_url"]
        if info.get("license"):
            item["license"] = info["license"][:64]
        assets.append(item)
    manifest = {"schema_version": 1, "generated_by": "opencode + niwo-render-everything skill",
                "notes": "图片来自 Pexels / Bing 图片搜索 / 圣路易斯联储 FRED（图表，公有领域）；"
                         "视频来自 Pexels，均已裁成 10 秒内短镜头。",
                "assets": assets}
    (BUNDLE / "content.json").write_text(json.dumps(CONTENT, ensure_ascii=False, indent=2), encoding="utf-8")
    (BUNDLE / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("content.json chars:", len(SCRIPT), "-> %.1f s" % (len(SCRIPT) / 6))
    print("assets:", len(assets), "(images",
          sum(1 for a in assets if a["kind"] == "image"), "videos",
          sum(1 for a in assets if a["kind"] == "video"), ")")

    r = subprocess.run(["python", str(SKILL / "scripts" / "validate_bundle.py"), str(BUNDLE)],
                       capture_output=True, text=True)
    print("--- validate rc", r.returncode, "---")
    print((r.stdout or "")[-2500:])
    print((r.stderr or "")[-800:])
    if r.returncode != 0:
        return
    zip_path = BUNDLE.parent / "美联储加息-素材包.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(BUNDLE / "content.json", "content.json")
        z.write(BUNDLE / "manifest.json", "manifest.json")
        for p in sorted((BUNDLE / "images").glob("*")):
            z.write(p, f"images/{p.name}")
        for p in sorted((BUNDLE / "videos").glob("*")):
            z.write(p, f"videos/{p.name}")
    print("ZIP:", zip_path, round(zip_path.stat().st_size / 1048576, 1), "MB")


if __name__ == "__main__":
    main()
