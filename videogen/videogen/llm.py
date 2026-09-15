"""Stage 16 (parity): LLM copywriting for designed-overlay cards.

Niwo's 画面设计 stage has an LLM rewrite card copy into punchy phrases
(e.g. "几家大公司都同意慢一点" -> "没人先停 / 共识存在，动作缺席").
This module does the same via DeepSeek (default) or Zhipu GLM, and falls
back to the rule-based copy if the API fails.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

from . import config

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
    for attempt in range(2):
        try:
            text = _chat(conf, json.dumps(payload, ensure_ascii=False))
            return _parse_json(text)
        except Exception as e:  # noqa: BLE001 - network/JSON hiccups: retry once
            last_err = e
    print(f"[llm] copy refinement failed, falling back to rules: {last_err}")
    return None


# ---------------- LLM 分镜导演（storyboard director） ----------------

DIRECTOR_SYSTEM = (
    "你是短视频分镜导演兼信息卡文案编辑。你会拿到一篇口播文案的句子列表和一份"
    "素材清单。你要像专业编导一样：把句子分组为镜头、给每个镜头指定素材、决定"
    "哪些镜头值得上信息设计卡、并为设计卡写出抓人的文案。严格基于给定内容，"
    "不得编造事实或数字。只输出一个 JSON 对象，不要 markdown 代码块。"
)


def design_shots(script: str, sentences: list[dict], assets: list[dict],
                 max_cards: int = 4, provider: str = "deepseek") -> dict | None:
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
                        "镜头短促 3-4 秒，节奏快",
                "profile": "人物特写——人物故事/访谈题材。偏爱 人物卡(person)/事实卡(fact)，"
                           "镜头 4-5 秒，稳重",
                "investigation": "深度复盘——事件复盘/调查报告。偏爱 时间线(timeline)/关系图(branches)/事实卡，"
                                 "镜头 4-6 秒",
                "opinion": "观点锐评——争议话题/评论。偏爱 大字卡(statement)/对比卡/清单，"
                           "镜头 3-4 秒快切，冲击力优先",
            },
            "输出": "在 theme 同级输出 style_pack 字段（值为 data/profile/investigation/opinion）",
            "节奏硬要求": "data/opinion 每镜 1-2 个子句单元（3-4 秒）；profile/investigation 每镜 2 个单元（4-6 秒）。"
                        "90 秒片总镜头数应为 18-26 个；宁可多切镜头，也不要出现超过 6 秒不换画面",
        },
        "分镜规则": [
            "输入是**子句单元**（逗号级短句，各带 index）：把 1-3 个语义连贯的子句组成一个镜头，"
            "按顺序覆盖所有单元且不重叠。永远不要把一个单元拆开跨镜头",
            "节奏：普通镜头配 1-2 个单元（约 3-5 秒），重要转折可用 3 个；"
            "目标不是句号对齐，而是每 3-5 秒换一次画面——全片镜头数应为 18-26 个",
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
            "card=compare 只用于句子同时提到美国/白宫/美方和中国/中方（"
            "left=美方做法 head≤4字 body≤12字；right=中方做法）",
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
    last_err = None
    for attempt in range(2):
        try:
            text = _chat(conf, json.dumps(payload, ensure_ascii=False))
            data = _parse_json(text)
            if isinstance(data, dict) and isinstance(data.get("shots"), list):
                return data
            last_err = ValueError("bad shape")
        except Exception as e:  # noqa: BLE001
            last_err = e
    print(f"[llm] storyboard planning failed, falling back to rules: {last_err}")
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
        print(f"[llm] vision check failed: {e}")
        return None
