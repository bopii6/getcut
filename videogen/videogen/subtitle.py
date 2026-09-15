"""ASS subtitle generation: clause captions burned into the panel's caption zone."""
from __future__ import annotations

from .planner import Plan

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font},70,&H00F5F3F0,&H00FFFFFF,&H00101010,&H7F000000,-1,0,0,0,100,100,0,0,1,0,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ts(ms: float) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{ms // 10:02d}"


def build_ass(plan: Plan, out_path) -> str:
    lines = [ASS_HEADER.format(font="Microsoft YaHei")]
    for c in plan.clauses:
        text = c.text.replace("{", "(").replace("}", ")")
        lines.append(
            f"Dialogue: 0,{_ts(c.start_ms)},{_ts(c.end_ms)},Sub,,0,0,0,,"
            f"{{\\an5\\pos({540},{1322})}}{text}"
        )
    content = "\n".join(lines) + "\n"
    out_path = __import__("pathlib").Path(out_path)
    out_path.write_text(content, encoding="utf-8")
    return content
