"""Minimal content/manifest/render protocol schemas, aligned with the niwo bundle format."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

HIGHLIGHT = re.compile(r"\[\[([^\[\]]+)\]\]")


class JobCancelled(Exception):
    """任务被用户停止：渲染子进程已杀掉，各阶段边界检查到这个就干净退出。"""


def _hook_line(item) -> str:
    """一行钩子标题统一成 "前半[[高亮]]后半"。

    getcut-bundle 技能投的包写的是 {"text","highlight"} 字典，内部样例写的是带
    [[..]] 的字符串——只按 str() 转会把字典原样打进成片标题。"""
    if not isinstance(item, dict):
        return str(item)
    text = str(item.get("text") or "")
    hl = str(item.get("highlight") or "")
    if not hl or "[[" in text:
        return text
    at = item.get("highlight_at")
    i = at if isinstance(at, int) and 0 <= at <= len(text) else text.find(hl)
    if i < 0:
        return text
    return text[:i] + "[[" + text[i:i + len(hl)] + "]]" + text[i + len(hl):]


@dataclass
class HookHeadline:
    lines: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, raw: dict) -> "HookHeadline":
        return cls(lines=[_hook_line(x) for x in raw.get("lines", [])])

    def plain(self, line: str) -> str:
        return HIGHLIGHT.sub(r"\1", line)

    def highlight_spans(self, line: str) -> list[tuple[int, int]]:
        """(start, end) char spans of highlighted text within the plain line."""
        spans, pos = [], 0
        for tok in re.split(r"(\[\[[^\[\]]+\]\])", line):
            if not tok:
                continue
            if tok.startswith("[[") and tok.endswith("]]"):
                spans.append((pos, pos + len(tok) - 4))
                pos += len(tok) - 4
            else:
                pos += len(tok)
        return spans


@dataclass
class Content:
    schema_version: int
    title: str
    script: str
    hook_headline: HookHeadline | None = None
    sources: list[str] = field(default_factory=list)
    pronunciations: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    @classmethod
    def load(cls, path: Path) -> "Content":
        raw = json.loads(path.read_text(encoding="utf-8"))
        hook = raw.get("hook_headline")
        return cls(
            schema_version=raw.get("schema_version", 1),
            title=raw["title"],
            script=raw["script"],
            hook_headline=HookHeadline.parse(hook) if hook else None,
            sources=raw.get("sources", []),
            pronunciations=raw.get("pronunciations", {}),
            notes=raw.get("notes", ""),
        )


@dataclass
class Asset:
    file: str
    kind: str
    summary: str = ""
    tags: list[str] = field(default_factory=list)
    script_anchor: str = ""
    source_url: str = ""

    @property
    def path_str(self) -> str:
        return self.file


@dataclass
class Manifest:
    schema_version: int
    assets: list[Asset] = field(default_factory=list)
    generated_by: str = ""

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            schema_version=raw.get("schema_version", 1),
            assets=[Asset(**{k: a[k] for k in ("file", "kind", "summary", "tags", "script_anchor", "source_url") if k in a})
                    for a in raw.get("assets", [])],
            generated_by=raw.get("generated_by", ""),
        )
