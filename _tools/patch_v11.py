#!/usr/bin/env python3
"""v11 part 2: route new variants, theme headline tick, exporter + director prompt."""
import json
from pathlib import Path

# ---------- TSX ----------
p = r'E:/短视频生成/videogen/renderer/src/NiwoVideo.tsx'
s = open(p, encoding='utf-8').read()

# headline highlight tick follows theme
s = s.replace("width: 10, background: T.red }} />", "width: 10, background: T.accent }} />")

# ShotView: render new variants inside the media box
old = '''            {shot.kind === 'panel' && shot.overlay?.variant === 'statement' ? (
              <StatementPanel spec={shot.overlay} />
            ) : null}'''
new = '''            {shot.kind === 'panel' && shot.overlay?.variant === 'statement' ? (
              <StatementPanel spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'stat' ? (
              <StatCard spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'branches' ? (
              <Branches spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'timeline' ? (
              <Timeline3 spec={shot.overlay} />
            ) : null}
            {shot.kind === 'panel' && shot.overlay?.variant === 'person' ? (
              <PersonCard spec={shot.overlay} />
            ) : null}'''
assert old in s, "shotview anchor"
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print("tsx routed")

# ---------- exporter: theme + generic passthrough for new variants ----------
p2 = r'E:/短视频生成/videogen/videogen/remotion_render.py'
s2 = open(p2, encoding='utf-8').read()
old2 = '''        elif shot.kind == "panel":
            v = o.get("variant", "fact")
            if v == "pace":'''
new2 = '''        elif shot.kind == "panel":
            v = o.get("variant", "fact")
            if v in ("stat", "branches", "timeline", "person"):
                s["overlay"] = {"variant": v, **{k: val for k, val in o.items() if k != "variant"}}
                shots.append(s)
                continue
            if v == "pace":'''
assert old2 in s2, "exporter anchor"
s2 = s2.replace(old2, new2)
# theme passthrough into props
s2 = s2.replace('''    return {
        "durationInFrames": max(int(plan.duration_ms / 1000 * 30) + 21, 30),''',
'''    props_out = {
        "durationInFrames": max(int(plan.duration_ms / 1000 * 30) + 21, 30),
        "accent": (plan.theme or {}).get("accent"),
        "accentSoft": (plan.theme or {}).get("accentSoft"),''')
s2 = s2.replace('''        "shots": shots,
        "clauses": [{"text": c.text, "startMs": round(c.start_ms), "endMs": round(c.end_ms)}
                    for c in plan.clauses],
    }''',
'''        "shots": shots,
        "clauses": [{"text": c.text, "startMs": round(c.start_ms), "endMs": round(c.end_ms)}
                    for c in plan.clauses],
    }
    props_out = {k: v for k, v in props_out.items() if v is not None}
    return props_out''')
open(p2, 'w', encoding='utf-8').write(s2)
print("exporter themed")

# ---------- planner: Plan gets theme attr ----------
p3 = r'E:/短视频生成/videogen/videogen/planner.py'
s3 = open(p3, encoding='utf-8').read()
s3 = s3.replace('''@dataclass
class Plan:
    shots: list[Shot] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    duration_ms: float = 0.0''',
'''@dataclass
class Plan:
    shots: list[Shot] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    duration_ms: float = 0.0
    theme: dict = field(default_factory=dict)''')
open(p3, 'w', encoding='utf-8').write(s3)
print("plan theme attr")

# ---------- director prompt: bigger card library + theme ----------
p4 = r'E:/短视频生成/videogen/videogen/llm.py'
s4 = open(p4, encoding='utf-8').read()
old4 = '''            "card=statement 用于有意象短句的镜头（title 3-7字 如'抢方向盘'，"
            "subtitle ≤12字，badge 2字，rows 可选最多2条，每条 text ≤10字）",'''
new4 = '''            "card=statement 用于有意象短句的镜头（title 3-7字 如'抢方向盘'，"
            "subtitle ≤12字，badge 2字，rows 可选最多2条，每条 text ≤10字）",
            "card=stat 用于含重要数字/金额/年份的镜头（label ≤4字，amount=数字+单位"
            "如'920 亿元'，desc ≤12字，year 可选4位年份徽章）",
            "card=branches 用于一句里一个原因引发多方后果的（label ≤4字，"
            "source ≤6字，targets 为3-4个短语各 ≤6字）",
            "card=person 用于介绍人物的镜头（kicker ≤6字英文或中文栏目名，"
            "title=姓名 ≤6字，caption ≤16字人物标签）",
            "card=timeline 用于讲历史脉络（title ≤6字，subtitle ≤10字，"
            "cols 为2-3个 {year:'4位年份', text:'≤8字'}）",
            "另外必须输出 theme：{\"accent\": \"主题色hex（根据选题气质从 "
            "#a44231 锈红/#d4a017 琥珀金/#2e6f6a 青绿/#3a5a8c 蓝钢 中选一个）\", "
            "\"accentSoft\": \"同色系亮一档的hex\"}，"
            "以及每个设计卡可选 kicker：≤10个字符的英文大写小标（如 FINANCIAL MODEL）",'''
assert old4 in s4, "llm rules anchor"
s4 = s4.replace(old4, new4)
s4 = s4.replace('''        "输出格式": {"shots": [{"sentences": [1], "asset": 0, "card": "callout 或 null",''',
'''        "输出格式": {"theme": {"accent": "#hex", "accentSoft": "#hex"},
                    "shots": [{"sentences": [1], "asset": 0, "card": "callout 或 null",''')
open(p4, 'w', encoding='utf-8').write(s4)
print("director prompt upgraded")
