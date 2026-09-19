"""模板定义：一套模板"能用哪些画面语言"，以及给导演的提示词怎么说。

为什么要有这个文件：以前模板的差异只写在渲染层（skin.ts / layouts.json）和导演提示词里
散着的一段 `if template == "zhigu"`，加一套模板要改四个地方。现在一模板一条定义：

- `cards` / `modes`：这套模板**支持哪几种画面语言**。导演只能从这里挑，选别的会被回落，
  所以不会出现"生成了一个这张模板画不出来的卡"。
- `director_note`：给导演的专项说明（这套模板的叙事气质、什么时候用哪种画面语言）。

注意边界：**模板只限定"能用哪些画面语言"，不规定"第几拍该出什么"**——哪一句配哪种卡
仍然由大模型按内容判断，模板只负责它看得懂哪些。
"""

from __future__ import annotations

# 卡片语汇（渲染端 NiwoVideo 的 ShotView 能画出来的）：
#   callout 数字标注 / compare 两栏对比 / fact 事实卡 / statement 大字卡
#   stat 数据卡 / branches 关系发散 / person 人物卡 / timeline 时间线
_BASE_CARDS = ("callout", "compare", "fact", "statement", "stat", "branches", "person", "timeline")


TEMPLATES_DEF: dict[str, dict] = {
    "editorial": {
        "cards": _BASE_CARDS,
        "director_note": "信息量最足的一套：纸卡上叠媒体窗与信息卡，适合把数据、对比、"
                         "结论一样样摆清楚。设计卡可以放到 4-6 张。",
    },
    "news": {
        # lower 骨架：满屏素材 + 底部信息条，卡走通用卡片（能画对比，画不了时间线那种细排版）
        "cards": ("callout", "compare", "fact", "statement", "stat", "person"),
        "director_note": "播报式：满屏画面 + 底部实色信息条，标题压在信息条上。"
                         "画面语言要克制，少堆卡片，让画面和口播走；卡片优先数字与对比。",
    },
    "bleed": {
        "cards": ("callout", "compare", "fact", "statement", "stat", "person"),
        "director_note": "沉浸式：素材铺满全屏，大标题压在画面上。适合情绪与人物，"
                         "卡片宁少勿多，一张卡就是一次强调。",
    },
    "data": {
        # 数据面板：左栏数据、右栏素材，最吃"数字/榜单/对比"
        "cards": ("callout", "compare", "stat", "fact", "statement"),
        "director_note": "仪表盘式：左边一栏是数据（数字、榜单、对比），右边一栏是素材。"
                         "有数字、有排名、有对比的句子优先上卡；纯叙事的句子留空让素材走。",
    },
    "poster": {
        # 大字报：画面就一个字大，只留最重的两种卡
        "cards": ("statement", "stat", "compare", "callout"),
        "director_note": "大字报式：一句一屏、超大字压在画面上，冲击力优先。"
                         "只在全句最有力的时候上卡，上了卡字要短（≤10 字），别堆信息。",
    },
    "zhigu": {
        "cards": (),
        "modes": ("chips", "tree", "table"),
        "director_note": "三段式：顶带大标题不动、底带字幕不动，中段全出血，"
                         "在「实拍素材」和「图形动作」之间快速切换，节奏要密。",
    },
    "macro": {
        # 宏观棱镜式：不吃素材，章节化的图形叙述（暗背景+金色）
        "cards": (),
        "modes": ("list", "bars", "line", "big", "cards", "grid", "vs", "arrow"),
        "director_note": "宏观解读式：按「章」叙述而不是按「镜」。每章=小标（01 / 消费）+金色论点大标题+副标，"
                         "正文用一种图形动作（列表/条形图/折线/大数字/卡链/网格/对比/时间箭头）逐条展开。"
                         "开场一章=一句话论点+三个关键词；结尾一章=总结+提问互动+口号。",
    },
}


# 舞台动作（三段式那类模板的"图形动作"）的说明——导演看这个决定给哪一拍上什么动作
_MODE_DESCRIPTIONS = {
    "chips": "句子点名了并列事物/动作时给 1-3 个 ≤6 字短词（如 [\"查资料\",\"写报告\"]），"
             "黄底黑字弹出，别超过 3 个",
    "tree": "句子在介绍「一个主体 + 它下面的几个东西」时给："
            "{center:{title:'≤8字主体', sub:'≤12字'}, children:['≤6字', ≤4 个]}，"
            "画面是中间主卡 + 虚线连到子项胶囊",
    "table": "句子在讲榜单/数据对比时给：{title:'≤10字', "
             "rows:[{name:'≤8字', value:'数字+单位', delta:'+x%', highlight:true?}，3-5 行]}，"
             "把要强调的一行设 highlight:true",
    # ---- macro（宏观棱镜式）的章节动作：一拍=一章，一章一种正文动作 ----
    "list": "开场论点或并列要点：{items:['≤8字', 3-4 个]，逐条弹出；最后一章可 goldLast:true 把末行变金句}",
    "bars": "一组正负同比数据（有涨有跌才用）：{rows:[{name:'≤8字', value:正负数, display:'+x.x%'}，2-3 行]}，"
            "零轴居中、正负各向两边伸",
    "line": "一个指标的时间趋势（≥6 个时点才用）：{unit:'%', ticks:[刻度数], "
            "points:[{x:'月份', y:数值}]}，逐点画线",
    "big": "一个数字就是论据：{number:'+2.7%', label:'≤8字 这数字是什么', deco:'dots'?}，超大金字",
    "cards": "推理链/递进结论：{rows:[{text:'≤14字', gold?}，2-4 张逐张弹]，最后一张常是金句设 gold}",
    "grid": "并列概念枚举：{items:[{title:'≤6字', sub:'≤10字'?}，4-6 个]}，2 列网格",
    "vs": "新旧/内外两个阵营对照：{left:{label:'≤6字', lines:['≤8字']}, "
          "right:{label:'≤6字', lines:['≤8字']}}，右栏金色",
    "arrow": "强调时滞/传导：{from:'≤6字', to:'≤6字', note:'≤14字'?}，一条从左往右生长的金色箭头",
}

# 设计卡配额 (最少, 最多, 至少几种)：按模板的信息密度给——大字报/沉浸式宁少勿多，
# 信息版可以铺满。这是"模板限定风格"的一部分，不是规定第几拍出什么。
_QUOTA = {
    "editorial": (4, 6, 3),
    "data": (4, 7, 3),
    "news": (2, 4, 2),
    "bleed": (2, 4, 2),
    "poster": (2, 4, 2),
}


def template_cards(template: str) -> tuple[str, ...]:
    """这套模板支持的卡片语汇；未知模板按 editorial 处理。"""
    return tuple((TEMPLATES_DEF.get(template) or TEMPLATES_DEF["editorial"]).get("cards") or ())


def template_modes(template: str) -> tuple[str, ...]:
    """这套模板支持的舞台动作（智谷三段式那类）；没有就是空。"""
    return tuple((TEMPLATES_DEF.get(template) or {}).get("modes") or ())


def director_note(template: str) -> str:
    return (TEMPLATES_DEF.get(template) or {}).get("director_note") or ""


def template_quota(template: str) -> tuple[int, int, int] | None:
    """设计卡配额 (最少, 最多, 至少几种)。"""
    return _QUOTA.get(template)


def mode_descriptions(template: str) -> dict[str, str]:
    """这套模板支持的舞台动作 → 说明。"""
    return {m: _MODE_DESCRIPTIONS.get(m, "") for m in template_modes(template)}
