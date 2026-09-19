#!/usr/bin/env python3
"""写 content.json + manifest.json（美联储9月加息）。"""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BUNDLE = Path(r"E:/短视频生成/bundle-fed-hike")

SCRIPT = (
    "白宫要利率降到百分之一，美联储偏偏加息。北京时间九月十七号凌晨，美联储全票通过，"
    "把联邦基金利率上调二十五个基点，到百分之三点七五到百分之四。这是二零二三年七月以来"
    "第一次加息，也是新主席沃什上任后的第一刀。别被二十五这个数字骗了。这不是鸽派加息，"
    "是鹰派开门。点阵图写明，今年底利率还要到百分之四到四点二五，十八位官员里十六位赞成"
    "年内再加一次。期货市场把年底再加一码的概率，打到了九成。沃什说得很硬：通胀降得不够快，"
    "金融条件也不够紧。美国物价已经连续六十五个月高于百分之二目标，七月PCE还有百分之三点七。"
    "特朗普当场开火，重申利率应该降到百分之一甚至更低。一边是白宫要廉价资金，一边是央行认账"
    "通胀没控住。美元当天大涨百分之零点七，黄金从高点砸下去一百多美元，两年期美债收益率创"
    "两年新高，美股尾盘跳水。美国房贷利率已经站上百分之七，借钱买房更贵了。对中国普通人，"
    "这次加息改不了你的房贷合同。但强美元会压人民币、抽走风险偏好。A股里科技成长会更敏感；"
    "出国、外贸、买美股的人，汇率波动才是正着的那一刀。真正要盯的不是这一次二十五基点，"
    "是沃什会不会把加息做成一轮周期。别指望加一次就停。市场已经不在问加不加，而在问年内"
    "还要加几次。这一刀打的是通胀，也打在白宫脸上。"
)

CONTENT = {
    "schema_version": 1,
    "title": "美联储时隔三年再加息，白宫喊话降到1%",
    "script": SCRIPT,
    "hook_headline": {"lines": ["白宫要降到[[1%]]", "美联储当场加息"]},
    "sources": ["美联储FOMC政策声明", "新浪财经", "每日经济新闻", "CNBC", "汇通财经"],
    "pronunciations": {
        "上调": "shang4 tiao2",
        "重申": "chong2 shen1",
        "偏好": "pian1 hao4",
        "沃什": "wo4 shi2",
    },
    "notes": (
        "成片形态按竖屏信息版收集素材（横构图 16:9），请在 Niwo 渲染界面把形态选成「竖屏信息版」，"
        "选成满屏竖屏会被裁切。10 段视频都已裁成 9 秒短镜头，无需再标选段。"
        "多音字已标注：上调(shang4 tiao2)、重申(chong2 shen1)、偏好(pian1 hao4)、沃什(wo4 shi2)。"
        "另有一处措辞提醒：「汇率波动才是正着的那一刀」的「正着」偏口语，若读起来别扭，"
        "可在 Niwo 里把它改成「正中」或「真正扎下去」，语意更顺。"
    ),
}

IMG = [
    ("01-whitehouse.jpg", "白宫北草坪与主楼外景，白天，草坪与旗帜清晰可见",
     ["白宫", "华盛顿", "美国政府"], "白宫要利率降到百分之一", "",
     "https://commons.wikimedia.org/wiki/File:White_House_North_Lawn_3-2007.jpg", "CC BY-SA 3.0"),
    ("02-fed-building.jpg", "华盛顿美联储大楼正面外景，白色石墙与柱廊，晴天",
     ["美联储大楼", "华盛顿", "建筑", "外景"], "美联储偏偏加息", "",
     "https://sd.ifeng.com/c/8czwWqDq0bY", ""),
    ("03-fed-rate-chart.png", "联邦基金利率长期走势折线图，横轴1955年至2025年，曲线末端可见近年快速抬升",
     ["利率走势", "联邦基金利率", "图表", "数据"],
     "点阵图写明，今年底利率还要到百分之四到四点二五", "",
     "https://fred.stlouisfed.org/", "Public Domain (FRED)"),
    ("04-warsh.jpg", "凯文·沃什穿深色西装站在印有美联储徽标的讲台前发言",
     ["沃什", "美联储主席", "发布会"], "也是新主席沃什上任后的第一刀", "",
     "https://www.fool.com/investing/2026/07/13/fed-chair-kevin-warsh-fail-headway-on-key-reform/", ""),
    ("05-presser.jpg", "三名西装男士站在美国国旗前的讲台旁，中间一位正在讲话",
     ["发布会", "讲台", "美国国旗", "发言"], "这不是鸽派加息，是鹰派开门", "",
     "https://www.pexels.com/photo/an-elderly-man-having-a-speech-in-front-of-the-microphone-of-a-podium-6950208/",
     "Pexels License"),
    ("06-warsh-hearing.jpg", "凯文·沃什在木质会议厅的听证会上举手发言，面前有话筒",
     ["沃什", "听证会", "发言", "美国"], "沃什说得很硬：通胀降得不够快", "",
     "https://en.sedaily.com/international/2026/05/18/kevin-warsh-to-take-office-as-fed-chair-at-white-house-on", ""),
    ("07-fed-building2.jpg", "美联储大楼正面外景，蓝天、旗杆与石砌柱廊",
     ["美联储大楼", "外景", "建筑", "国旗"], "北京时间九月十七号凌晨，美联储全票通过", "", "", ""),
    ("08-market-screen.jpg", "屏幕上显示连续下跌的红色K线与均线，行情走弱",
     ["行情", "下跌", "K线", "屏幕"], "美股尾盘跳水", "", "", ""),
    ("09-usd-closeup.jpg", "多张一百美元纸币叠放的近景，可看到钞票纹理与面额",
     ["美元", "钞票", "近景", "货币"], "美元当天大涨百分之零点七", "",
     "https://www.pexels.com/photo/a-close-up-shot-of-paper-bills-6468225/", "Pexels License"),
    ("10-cpi-chart.png", "美国消费者物价指数同比走势折线图，曲线持续上行",
     ["通胀走势", "CPI", "图表", "数据"], "美国物价已经连续六十五个月高于百分之二目标", "",
     "https://fred.stlouisfed.org/", "Public Domain (FRED)"),
    ("11-supermarket.jpg", "超市里推着购物车挑选蔬果的顾客，货架整齐",
     ["超市", "购物", "货架", "物价"], "七月PCE还有百分之三点七", "",
     "https://www.pexels.com/photo/woman-with-braids-in-blue-denim-jacket-holding-a-shopping-cart-4971945/",
     "Pexels License"),
    ("12-trump.jpg", "特朗普在椭圆形办公室的桌前低头签署文件，身后是美国国旗与总统旗",
     ["特朗普", "白宫", "签署", "椭圆办公室"], "特朗普当场开火", "",
     "https://commons.wikimedia.org/wiki/File:Trump_signing_Executive_Order_13780.jpg", "Public domain"),
    ("13-whitehouse2.jpg", "白宫主楼正面，草坪与喷泉，白天",
     ["白宫", "建筑", "美国"], "一边是白宫要廉价资金", "",
     "https://commons.wikimedia.org/wiki/File:The_White_House_North_Lawn_(5945796963).jpg", "CC BY 2.0"),
    ("14-gold.jpg", "深色背景上一块刻着纯金、GOLD、999.9字样的金条特写",
     ["金条", "黄金", "贵金属", "特写"], "黄金从高点砸下去一百多美元", "",
     "https://www.pexels.com/photo/close-up-of-gold-bar-with-inscriptions-35065436/", "Pexels License"),
    ("15-gold-coins.jpg", "黑色台面上散落着多枚不同国家的金币",
     ["金币", "黄金", "投资", "贵金属"], "黄金从高点砸下去一百多美元", "",
     "https://www.pexels.com/photo/gold-round-coins-on-black-surface-8442324/", "Pexels License"),
    ("16-wallstreet-sign.jpg", "纽约华尔街路口的街牌与红绿灯，背景是高楼",
     ["华尔街", "路牌", "纽约", "街景"], "真正要盯的不是这一次二十五基点", "", "", ""),
    ("17-mortgage-docs.jpg", "房屋贷款合同文件与一串钥匙放在桌面上",
     ["房贷", "合同", "钥匙", "文件"], "美国房贷利率已经站上百分之七", "",
     "https://www.builderonline.com/data-analysis/mortgage-outlook-what-2021-holds-for-buyers-builders-and-lenders_o", ""),
    ("18-yuan-100.jpg", "一百元人民币纸币正面，印有人民大会堂图案",
     ["人民币", "百元", "纸币", "钞票"], "对中国普通人，这次加息改不了你的房贷合同", "",
     "https://www.waizi.org.cn/law/5912.html", ""),
    ("19-bank-counter.jpg", "银行换汇柜台窗口，玻璃后是外币牌价与柜员",
     ["银行", "换汇", "柜台", "外币"], "但强美元会压人民币、抽走风险偏好", "",
     "https://www.pexels.com/photo/man-exchanging-money-12008048/", "Pexels License"),
    ("20-ashare.jpg", "上海陆家嘴金融区的高楼群与黄浦江，白天，东方明珠塔清晰可见",
     ["上海", "陆家嘴", "金融区", "中国"], "A股里科技成长会更敏感", "",
     "https://www.pexels.com/photo/skyline-of-lujiazui-financial-district-shanghai-38185635/", "Pexels License"),
    ("21-airport.jpg", "机场航站楼里拖着行李的旅客经过航班信息屏",
     ["机场", "旅客", "出行", "航班屏"], "出国、外贸、买美股的人", "",
     "https://www.pexels.com/photo/screen-in-airport-terminal-6544058/", "Pexels License"),
    ("22-port.jpg", "集装箱码头，成排集装箱与蓝色岸桥吊机，有货轮停靠",
     ["港口", "集装箱", "外贸", "货运"], "出国、外贸、买美股的人", "",
     "https://www.pexels.com/photo/containers-in-harbor-15346128/", "Pexels License"),
    ("23-nyc-skyline.jpg", "纽约曼哈顿天际线黄昏剪影，高楼群与落日",
     ["纽约", "天际线", "黄昏", "城市"], "市场已经不在问加不加，而在问年内还要加几次", "",
     "https://www.pexels.com/photo/silhouette-of-city-buildings-during-sunset-8569166/", "Pexels License"),
    ("24-calculator.jpg", "桌面上的计算器与财务图表，旁边有笔和纸张",
     ["计算器", "财务", "办公桌", "图表"], "到百分之三点七五到百分之四", "",
     "https://www.pexels.com/photo/calculator-on-top-of-the-paper-7580854/", "Pexels License"),
    ("25-coins.jpg", "硬币成堆散落在白色桌面，浅景深",
     ["硬币", "存款", "零钱", "桌面"], "别指望加一次就停", "",
     "https://www.pexels.com/photo/coins-on-white-surface-12955794/", "Pexels License"),
    ("26-stocks-screen.jpg", "证券交易所内整面墙的指数显示屏，密密麻麻排列着代码与行情",
     ["交易所", "行情", "屏幕", "指数"], "十八位官员里十六位赞成年内再加一次", "",
     "https://commons.wikimedia.org/wiki/File:Frankfurt_Stock_Exchange_(Ank_Kumar)_08.jpg", "CC BY-SA 4.0"),
    ("27-business-meeting.jpg", "会议室里几个人围着铺满图表的桌面讨论",
     ["会议", "数据分析", "讨论", "办公"], "期货市场把年底再加一码的概率，打到了九成", "", "", ""),
    ("28-china-city.jpg", "北京望京CBD高楼天际线，多栋现代写字楼",
     ["北京", "天际线", "中国", "城市"], "对中国普通人，这次加息改不了你的房贷合同", "",
     "https://commons.wikimedia.org/wiki/File:Dawangjing_Skyline_20210403_183523.jpg", "CC BY-SA 4.0"),
    ("29-china-cbd.jpg", "北京建外SOHO与央视总部大楼，傍晚天色",
     ["北京", "CBD", "地标", "中国"], "这一刀打的是通胀，也打在白宫脸上", "",
     "https://commons.wikimedia.org/wiki/File:Jianwai_SOHO_and_CCTV_Headquarters_2015.jpg", "CC BY-SA 4.0"),
]

VID = [
    ("01-wallstreet.mp4", "纽约华尔街街景，两侧高楼与来往行人车辆", ["华尔街", "街道", "建筑", "纽约"],
     "美股尾盘跳水", "https://www.pexels.com/video/finance-nyse-wall-street-new-york-city-4319342/"),
    ("02-money.mp4", "点钞机清点美元纸币的特写", ["点钞", "美元", "现金", "特写"],
     "美元当天大涨百分之零点七", "https://www.pexels.com/video/a-person-counting-money-5466769/"),
    ("03-market.mp4", "屏幕上滚动的行情图表与交易数据", ["行情屏", "图表", "交易", "屏幕"],
     "两年期美债收益率创两年新高", "https://www.pexels.com/video/stock-market-data-analysis-on-dual-screens-38484636/"),
    ("04-stockmarket.mp4", "股市交易大厅屏幕与滚动行情数据", ["股市", "金融", "交易", "屏幕"],
     "市场已经不在问加不加", "https://www.pexels.com/video/38209367/"),
    ("05-gold.mp4", "成排金条的特写，金条上刻着FINE GOLD 999.9", ["金条", "黄金", "贵金属", "特写"],
     "黄金从高点砸下去一百多美元", ""),
    ("06-skyline.mp4", "纽约城市天际线航拍移动镜头", ["天际线", "航拍", "城市", "建筑"],
     "真正要盯的不是这一次二十五基点", "https://www.pexels.com/video/drone-footage-of-city-12197806/"),
    ("07-traffic.mp4", "夜间城市车流延时，车灯拉出光带", ["车流", "夜景", "城市", "延时"],
     "别指望加一次就停", "https://www.pexels.com/video/night-traffic-on-junction-in-city-10433645/"),
    ("08-bank.mp4", "城市中的银行建筑与街景", ["银行", "建筑", "城市", "金融"],
     "但强美元会压人民币", "https://www.pexels.com/video/illustration-of-rate-5849626/"),
    ("09-laptop.mp4", "办公桌上的笔记本电脑显示行情图表，手在键盘上操作", ["笔记本", "图表", "办公", "手部"],
     "期货市场把年底再加一码的概率", "https://www.pexels.com/video/hands-typing-in-a-laptop-7055337/"),
    ("10-port.mp4", "港口集装箱码头的吊装作业与货轮", ["港口", "集装箱", "外贸", "货运"],
     "出国、外贸、买美股的人", ""),
]


def build_manifest():
    assets = []
    for name, summary, tags, anchor, _x, src, lic in IMG:
        item = {"file": f"images/{name}", "kind": "image", "summary": summary,
                "tags": tags, "script_anchor": anchor}
        if src:
            item["source_url"] = src
        if lic:
            item["license"] = lic
        assets.append(item)
    for name, summary, tags, anchor, src in VID:
        item = {"file": f"videos/{name}", "kind": "video", "summary": summary,
                "tags": tags, "script_anchor": anchor}
        if src:
            item["source_url"] = src
        item["license"] = "Pexels License" if src else ""
        if not item["license"]:
            item.pop("license")
        assets.append(item)
    return {
        "schema_version": 1,
        "generated_by": "opencode + niwo-render-everything 1.0.0",
        "notes": ("竖屏信息版取向：视频均为横构图 1080p、已裁成 9 秒短镜头（无需再标选段）；"
                  "图片全部为横构图大图。manifest 顺序跟随口播文案推进。"
                  "图表来自 FRED（公有领域）；人物与机构实拍来自公开新闻页面；其余实拍来自 Pexels。"),
        "assets": assets,
    }


def main():
    (BUNDLE / "content.json").write_text(
        json.dumps(CONTENT, ensure_ascii=False, indent=2), encoding="utf-8")
    (BUNDLE / "manifest.json").write_text(
        json.dumps(build_manifest(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("script chars:", len(SCRIPT), "≈", round(len(SCRIPT) / 6, 1), "s")
    print("images:", len(IMG), "videos:", len(VID))


if __name__ == "__main__":
    main()
