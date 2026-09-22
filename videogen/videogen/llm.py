"""Stage 16 (parity): LLM copywriting for designed-overlay cards.

Niwo's 画面设计 stage has an LLM rewrite card copy into punchy phrases
(e.g. "几家大公司都同意慢一点" -> "没人先停 / 共识存在，动作缺席").
This module does the same via DeepSeek (default) or Zhipu GLM, and falls
back to the rule-based copy if the API fails.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import requests

from . import config, templates

log = logging.getLogger(__name__)


def _rule_card(line: str) -> str | None:
    """从提示词的一行"card=xxx 用于…"里取出卡名；不是卡片规则行就返回 None。"""
    m = re.match(r"\s*card=([a-z_]+)", line or "")
    return m.group(1) if m else None

PROVIDERS = {
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "model": "deepseek-chat",
        "key": config.DEEPSEEK_API_KEY,
    },
    "zhipu": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash",
        "key": config.ZHIPU_API_KEY,
    },
}

SYSTEM = (
    "你是短视频信息卡的文案编辑。你的任务是把卡片上的文案改写得更抓人，"
    "但必须严格基于给出的口播文案内容，不得编造任何新事实、新数字。"
    "只输出一个 JSON 对象，不要 markdown 代码块，不要解释。"
)

RULES = """改写要求（字数是硬约束，超长会被截断）：
- callout: label 2-4字短语；number 和 caption 保持事实数字不改，caption ≤12字
- compare: label ≤4字；title 4-6字（冲突式短语）；subtitle ≤8字；
  left/right head ≤4字（立场名）；left/right body ≤12字（该方做法的概括）
- fact: label ≤4字；card.title ≤8字（观点化提炼）；card.body ≤14字
- statement: label ≤4字；title 3-7字（意象化短语，如"抢方向盘"）；subtitle ≤12字；badge 2字
- title_card: label 格式"XX｜XX"共4-8字；keyword 2-4字（全片题眼）
- quote_card: label ≤4字（时间/场景）；quote 4-8字（金句）
全部用简体中文，短句，有冲击力，不要书面腔。"""


def _chat(provider: dict, user_prompt: str, timeout: int = 90) -> str:
    key = provider["key"]
    r = requests.post(
        provider["url"],
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": provider["model"],
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": user_prompt}],
            "temperature": 0.7,
            "response_format": {"type": "json_object"},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def refine_copy(script: str, cards: list[dict], provider: str = "deepseek") -> dict | None:
    """Rewrite designed-card copy via LLM.

    cards: [{index, kind, variant?, sentence, current:{...fields}}]
    returns {"shots": {"<index>": {...}}, "title_card": {...}, "quote_card": {...}}
            or None on failure (caller falls back to rule-based copy).
    """
    conf = PROVIDERS.get(provider)
    if not conf or not conf["key"]:
        return None
    payload = {
        "口播文案": script,
        "卡片列表": cards,
        "改写要求": RULES,
        "输出格式": {
            "shots": {"<卡片index>": {"改写后的字段…": "…"}},
            "title_card": {"label": "…", "keyword": "…"},
            "quote_card": {"label": "…", "quote": "…"},
        },
    }
    last_err = None
    for _attempt in range(2):
        try:
            text = _chat(conf, json.dumps(payload, ensure_ascii=False))
            return _parse_json(text)
        except Exception as e:  # noqa: BLE001 - network/JSON hiccups: retry once
            last_err = e
    # 降级要留痕：静默回落到规则引擎时，"为什么文案比平时平"没人答得上来。
    log.warning("copy refinement failed, falling back to rules", exc_info=last_err)
    return None


# ---------------- LLM 分镜导演（storyboard director） ----------------

DIRECTOR_SYSTEM = (
    "你是短视频分镜导演兼信息卡文案编辑。你会拿到一篇口播文案的句子列表和一份"
    "素材清单。你要像专业编导一样：把句子分组为镜头、给每个镜头指定素材、决定"
    "哪些镜头值得上信息设计卡、并为设计卡写出抓人的文案。严格基于给定内容，"
    "不得编造事实或数字。只输出一个 JSON 对象，不要 markdown 代码块。"
)


def design_shots(script: str, sentences: list[dict], assets: list[dict],
                 max_cards: int = 4, provider: str = "deepseek",
                 template: str | None = None) -> dict | None:
    """LLM 分镜规划：句子分组 + 素材分配 + 设计卡选择与文案，一次调用完成。

    sentences: [{index, text}]（不含首尾——首尾由片头卡/金句卡固定承担）
    assets:    [{index, kind, tags, summary}]
    returns {"shots": [{sentences, asset, card, chapterLabel, ...copy}]} or None.
    """
    conf = PROVIDERS.get(provider)
    if not conf or not conf["key"]:
        return None
    payload = {
        "口播文案": script,
        "句子列表": sentences,
        "素材清单": assets,
        "风格包（必须先选，决定整条片子的形态）": {
            "说明": "按选题气质四选一，不同主题要选不同风格包，让每条片子的形态都不一样",
            "选项": {
                "data": "数据快报——行情/财报/市场题材。偏爱 数据卡(stat)/对比卡(compare)/数字标注(callout)，"
                        "镜头可略短 3.5 秒左右",
                "profile": "人物特写——人物故事/访谈题材。偏爱 人物卡(person)/事实卡(fact)，稳重",
                "investigation": "深度复盘——事件复盘/调查报告。偏爱 时间线(timeline)/关系图(branches)/事实卡",
                "opinion": "观点锐评——争议话题/评论。偏爱 大字卡(statement)/对比卡/清单，冲击力优先",
            },
            "输出": "在 theme 同级输出 style_pack 字段（值为 data/profile/investigation/opinion）",
            "节奏硬要求": "每个镜头 3.5-4.5 秒；4.8 秒是硬上限（超了会被强制再切一刀）。"
                        "90 秒的片子应是 20-25 个镜头。这是固定节奏，不要自行加快或放慢",
        },
        "分镜规则": [
            "输入是**子句单元**（逗号级短句，各带 index）：把 2-3 个语义连贯的子句组成一个镜头，"
            "按顺序覆盖所有单元且不重叠。永远不要把一个单元拆开跨镜头",
            "节奏：普通镜头配 2 个单元（3.5-4.5 秒），最多 3 个；"
            "目标不是句号对齐，而是每 4 秒左右换一次画面——全片镜头数应为 20-25 个",
            "每组指定一个素材 index（只能用素材清单里的 index）",
            "素材匹配优先级（重要）：先看画面主体是否对得上——句子讲具体人物时必须用该人物的素材"
            "（人物照片比不相关的视频更好）；讲市场行情用行情素材；讲网络安全用安全类素材；"
            "讲数据中心用机房素材。",
            "视频占比硬要求：在匹配的前提下尽量用 kind=video 的素材——目标是一半以上的镜头配视频；"
            "只有某句确实找不到匹配视频时才用图片。同一个视频最多用两次且不相邻",
            "每个镜头（包括设计卡镜头）都必须指定素材：设计卡会以半透明形式叠在素材画面上，"
            "所以给设计卡也要挑一张贴合该句内容的素材（优先视频）",
            "card 为 null 表示普通实拍镜头（多数镜头应该是这种）",
            f"设计卡最多 {max_cards} 个，用在最有信息量或最有冲突感的句子上；"
            "相邻镜头不要连续用设计卡",
            "card=callout 只用于句子里有明确数字的（number 用阿拉伯数字+单位，"
            "如 3800字 / 6个月；caption ≤12字说明这个数字是什么）",
            "card=compare 只用于句子明确出现对立双方时（两个国家、两家公司、两个阵营等，"
            "left/right 分别概括双方的做法，head≤4字 body≤12字）",
            "card=fact 用于单个关键事实句（title≤8字 观点化提炼，body≤14字）",
            "card=statement 用于有意象短句的镜头（title 3-7字 如'抢方向盘'，"
            "subtitle ≤12字，badge 2字，rows 可选最多2条，每条 text ≤10字）",
            "card=stat 用于含重要数字/金额的镜头（label ≤4字，amount=数字+单位"
            "如'920 亿元'，desc ≤12字；year 只有在文案里明确出现年份时才填，否则必须省略，严禁编造）",
            "card=branches 用于一句里一个原因引发多方后果的（label ≤4字，"
            "source ≤6字，targets 为3-4个短语各 ≤6字）",
            "card=person 用于介绍人物的镜头（kicker ≤6字英文或中文栏目名，"
            "title=姓名 ≤6字，caption ≤16字人物标签）",
            "card=timeline 用于讲历史脉络（title ≤6字，subtitle ≤10字，"
            "cols 为2-3个 {year:'4位年份', text:'≤8字'}）",
            "另外必须输出 theme，格式为 {\"accent\": \"主题色hex（根据选题气质从 "
            "#a44231 锈红/#d4a017 琥珀金/#2e6f6a 青绿/#3a5a8c 蓝钢 中选一个）\", "
            "\"accentSoft\": \"同色系亮一档的hex\"}，"
            "以及每个设计卡可选 kicker：≤10个字符的英文大写小标（如 FINANCIAL MODEL）",
            "chapterLabel 2-4字，概括这个镜头的画面主题（如 机房/筹码/方向盘）",
            "设计卡数量硬要求：13 个左右镜头里，设计卡必须 4-6 个，且类型必须多样化"
            "（stat/compare/fact/branches/timeline/person 至少用 3 种不同类型），"
            "其余为普通实拍镜头",
            "必须输出 theme 字段（accent 与 accentSoft 两个 hex）",
        ],
        "输出格式": {"theme": {"accent": "#hex", "accentSoft": "#hex"},
                    "shots": [{"sentences": [1], "asset": 0, "card": "callout 或 null",
                          "chapterLabel": "机房",
                          "label": "只在该镜头是设计卡时给出",
                          "title": "只在该镜头是设计卡时给出",
                          "subtitle": "只在该镜头是设计卡时给出",
                          "number": "只有 callout 给",
                          "caption": "只有 callout 给",
                          "badge": "只在该镜头是设计卡时给出",
                          "left": "只有 compare 给: {head, body}",
                          "right": "只有 compare 给: {head, body}",
                          "card_title": "只有 fact 给",
                          "card_body": "只有 fact 给",
                          "rows": "只有 statement 给: [{code, text}]"}],
                    "重要": "普通实拍镜头（card=null）只保留 sentences/asset/card/chapterLabel 四个字段，"
                          "设计卡也只保留自己类型需要的字段，不要输出无关字段，更不要出现'仅xx'这类占位文字",
        },
    }
    # ---------- 模板语汇：把「这套模板能用哪些画面语言」收进提示词 ----------
    # 以前这里是一段 if template == "zhigu"，加一套模板就得改这个函数。现在模板的定义
    # 在 videogen/templates.py：能画哪几种卡、有没有舞台动作、给导演的专项说明。
    # 边界要清楚：模板**只限定可用的画面语言**，不规定"第几拍该出什么"——
    # 哪一句配哪种卡仍由导演按内容判断，它只是挑不出这套模板画不出来的东西。
    vocab_note = templates.director_note(template)
    if vocab_note:
        payload["模板专项"] = vocab_note

    cards = templates.template_cards(template)
    shot_fmt = payload["输出格式"]["shots"][0]
    if cards and cards != templates.template_cards("editorial"):
        # 不支持的卡从规则里删掉，并把取值收成枚举
        payload["分镜规则"] = [ln for ln in payload["分镜规则"]
                                if _rule_card(ln) is None or _rule_card(ln) in cards]
        shot_fmt["card"] = " 或 ".join([*cards, "null"])
        quota = templates.template_quota(template)
        if quota:
            lo, hi, kinds = quota
            for i, ln in enumerate(payload["分镜规则"]):
                if ln.startswith("设计卡数量硬要求"):
                    payload["分镜规则"][i] = (
                        f"设计卡数量：全片 {lo}-{hi} 张，类型从 {'/'.join(cards)} 里挑，"
                        f"至少用 {kinds} 种不同的；其余为普通实拍镜头")
                    break

    modes = templates.template_modes(template)
    if modes:
        descriptions = templates.mode_descriptions(template)
        payload["舞台动作（本模板特有）"] = {
            "说明": "这套模板的中段在「实拍素材」和「图形动作」之间切换，"
                    "每个镜头可选输出 stage 字段（不输出＝纯实拍镜头）",
            "可选的 stage 动作": {m: descriptions.get(m, "") for m in modes},
            "硬要求": "全片至少 1/3 的镜头带 stage 动作；"
                     "重要数字句优先用 table，介绍产品/公司/版本优先用 tree；"
                     "其余保持纯实拍（不要为了用而用）",
        }
        # 通用的「输出格式」段写着"普通镜头只保留四个字段"，会把 stage 挤掉——对本模板放行
        shot_fmt["stage"] = "带舞台动作的镜头给：" + " / ".join(f"{m} 对象" for m in modes)
        payload["输出格式"]["重要"] = (
            "普通实拍镜头保留 sentences/asset/card/chapterLabel 四个字段，"
            "有舞台动作的镜头再加一个 stage 字段；设计卡只保留自己类型需要的字段，"
            "不要输出无关字段，更不要出现'仅xx'这类占位文字")
    last_err = None
    for _attempt in range(2):
        try:
            text = _chat(conf, json.dumps(payload, ensure_ascii=False))
            data = _parse_json(text)
            if isinstance(data, dict) and isinstance(data.get("shots"), list):
                return data
            last_err = ValueError("bad shape")
        except Exception as e:  # noqa: BLE001
            last_err = e
    log.warning("storyboard planning failed, falling back to rules",
                exc_info=last_err)
    return None


def design_chapters(script: str, units: list[dict], assets: list[dict],
                    provider: str = "deepseek") -> dict | None:
    """macro（宏观棱镜式）专用导演：把子句单元组织成「章」，一章一种图形动作。

    与 design_shots 的区别：macro 不按 4 秒一镜切素材，而是按叙述逻辑分章
    （3-8 个单元一章），章内元素跟着句子逐个弹出。素材只用来挑一张当暗背景。
    returns {"bg_asset": int|None, "chapters": [{kicker,title,sub,caption,rule,
              block:{type,...}, units:[index,...]}]} or None.
    """
    conf = PROVIDERS.get(provider)
    if not conf or not conf["key"]:
        return None
    payload = {
        "口播文案": script,
        "子句单元": units,
        "素材清单（只用来挑一张当全片暗背景，选最有选题氛围的一张图）": assets,
        "章节规则": [
            "输入是**子句单元**（逗号级短句，各带 index）：把语义连贯的 3-8 个单元组成一章，"
            "按顺序覆盖所有单元且不重叠，一个单元不能拆开",
            "全片 5-9 章。开头一章=钩子（一句话论点+3 个关键词，block 用 list）；"
            "结尾一章=总结+提问互动+口号（block 用 list，末行 gold）；中间按内容分章",
            "每章输出 kicker（如 01 / 消费 或 总览 或 02 / TRANSMISSION）、"
            "title（金色论点大标题 ≤9 字）、sub（限定语 ≤14 字，可选）",
            "每章一种正文动作 block.type，从 list/bars/line/big/cards/grid/vs/arrow 里按内容挑："
            "并列要点=list；一组正负数据=bars；时间趋势(≥6 个时点)=line；单个关键数字=big；"
            "推理链/递进=cards；并列概念=grid；两个阵营对照=vs；时滞传导=arrow。"
            "一章没有合适的动作就不给 block（纯标题章），但全片至少 2/3 的章要有 block",
            "数据铁律：bars/line/big 里的数字只能来自口播文案里出现的数字，"
            "严禁编造或换算文案里没有的数。文案没给时间趋势就别用 line。"
            "注意文案可能把数字写成中文（如「二百四十三亿美元」），"
            "block 里请换算成阿拉伯数字输出（value: 243, display: '+243亿美元'），"
            "校验不过的行会被整行丢弃",
            "可选输出 caption（本章收束的一句金线小字 ≤14 字）和 rule:true（章尾金色分隔线，"
            "中间章节建议给）",
            "可选输出 bg_asset：从素材清单挑一个 index 当全片暗背景（优先氛围图）",
        ],
        "输出格式": {"bg_asset": 0,
                    "chapters": [{"kicker": "01 / 消费", "title": "消费迈不开",
                                  "sub": "今年前8个月 · 同比变化",
                                  "block": {"type": "bars", "rows": [
                                      {"name": "出口", "value": 14.6, "display": "+14.6%"}]},
                                  "caption": "可选", "rule": True, "units": [3, 4, 5]}],
                    "block 字段（type 对应的固定字段名，照抄别造新名字）": {
                        "list": {"items": ["≤8字", "..."]},
                        "bars": {"rows": [{"name": "名称", "value": 14.6, "display": "+14.6%"}]},
                        "line": {"unit": "%", "ticks": [10, 0, -10], "points": [{"x": "3月", "y": 1.7}]},
                        "big": {"number": "+2.7%", "label": "是什么", "deco": "dots?"},
                        "cards": {"rows": [{"text": "≤14字", "gold": False}]},
                        "grid": {"items": [{"title": "≤6字", "sub": "≤10字"}]},
                        "vs": {"left": {"label": "≤6字", "lines": ["≤10字"]},
                               "right": {"label": "≤6字", "lines": ["≤10字"]}},
                        "arrow": {"from": "≤6字", "to": "≤6字", "note": "≤14字"},
                    }},
    }
    last_err = None
    for _attempt in range(2):
        try:
            text = _chat(conf, json.dumps(payload, ensure_ascii=False))
            data = _parse_json(text)
            if isinstance(data, dict) and isinstance(data.get("chapters"), list) and data["chapters"]:
                return data
            last_err = ValueError("bad shape")
        except Exception as e:  # noqa: BLE001
            last_err = e
    log.warning("chapter planning failed, falling back to rules",
                exc_info=last_err)
    return None


def vision_check(image_path: Path, question: str, timeout: int = 60) -> dict | None:
    """视觉校验（对齐 niwo checking_visuals）：用 GLM-4V 看一帧画面并回答。

    returns {"ok": bool, "reason": str} or None on failure.
    """
    conf = PROVIDERS.get("zhipu")
    if not conf or not conf["key"]:
        return None
    import base64
    b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
    key = conf["key"]
    try:
        r = requests.post(
            conf["url"],
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": "glm-4v-flash",
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                        {"type": "text", "text": question +
                         ' 只输出 JSON：{"ok": true/false, "reason": "简短原因"}'},
                    ],
                }],
                "temperature": 0.1,
            },
            timeout=timeout,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
        return _parse_json(text)
    except Exception as e:  # noqa: BLE001
        log.warning("vision check failed", exc_info=e)
        return None
