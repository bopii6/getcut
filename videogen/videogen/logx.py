# -*- coding: utf-8 -*-
"""结构化日志：一行一个 JSON，出事时靠 rid 把一次请求串起来。

为什么单独一个模块（2026-09-22）：
    在此之前全仓**零 logging** —— 54 处 `print`，`uvicorn.run(log_level="warning")`
    连访问日志都关着。后果是"出事只能人肉翻 docker logs"，而 docker 日志
    容器一重启就断档。更糟的是三样东西对不上号：这是哪一次请求、哪一条任务、
    哪一分钟的日志 —— 客户说"我那单没声"，你根本无从查起。

三条规矩（改这个文件之前先读完）：
  1. **一行一个 JSON 对象**，键固定 `ts / level / logger / msg`，其余按需追加。
     这样 `docker logs videogen | jq 'select(.level=="ERROR")'` 直接可用，
     将来接 Loki / 云日志服务不用改代码。
  2. **请求 ID 走 contextvar**，不走参数。中间件发一个 rid 放进去，同一次
     请求里打的所有日志（包括跑在线程池里的同步端点）自动带上它。
     反例是把 rid 当参数一路往下传 —— 那要改几十个函数签名，没人会做完，
     于是第 3 天就有人漏传，日志重新对不上号。
  3. **不许把 query string 打进日志**。本站有 `?token=` 这条带主钥匙的通道，
     access 日志只记 `request.url.path`（见 server._access_log）。

输出去向：stdout（12-factor）。容器日志交给 docker 的轮转配置
（docker-compose.yml 的 logging 段 / deploy_new.sh 的 --log-opt），不要自己开文件。
"""
from __future__ import annotations

import json
import logging
import os
import sys
import time
from contextvars import ContextVar

# 当前请求的 rid。空串 = 不在请求上下文里（后台线程、CLI），日志就不带这个键。
RID: ContextVar[str] = ContextVar("videogen_rid", default="")

# LogRecord 自带的属性。调用方用 extra={"job": ...} 传进来的键**不在**这里，
# 所以拿这个集合当白名单的反面，就能把 extra 原样摊平进 JSON。
_STD = frozenset({
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "message", "asctime",
})

_HANDLER_TAG = "_videogen_json"

# 第三方为**它自己的** formatter 递的键：值是模板不是成品 —— uvicorn 的
# color_message 里还留着没替换的 %d 和 ANSI 色码（它自己的着色 formatter 才会
# 拿去渲染）。摊进我们的 JSON = 同一句话出现两遍，其中一遍是坏的。
_FOREIGN_FMT = frozenset({"color_message"})


def _ts(epoch: float) -> str:
    """RFC3339 本地时间，毫秒精度。日志要能直接读，别给人看 Unix 时间戳。"""
    lt = time.localtime(epoch)
    tz = time.strftime("%z", lt)
    if not tz:
        # 部分平台（Windows 的某些 CRT 版本）%z 返回空串。时区尾巴丢了就跨机器
        # 对不了时序，宁可按本地时区自己算一个出来。
        off = -time.timezone if lt.tm_isdst <= 0 else -time.altzone
        tz = "%s%02d%02d" % ("+" if off >= 0 else "-",
                             abs(off) // 3600, abs(off) % 3600 // 60)
    if len(tz) == 5:                       # +0800 -> +08:00
        tz = tz[:3] + ":" + tz[3:]
    return "%s.%03d%s" % (time.strftime("%Y-%m-%dT%H:%M:%S", lt),
                          int((epoch - int(epoch)) * 1000), tz)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": _ts(record.created), "level": record.levelname,
               "logger": record.name, "msg": record.getMessage()}
        rid = RID.get()
        if rid:
            out["rid"] = rid
        for k, v in record.__dict__.items():
            if k in _STD or k in _FOREIGN_FMT or k.startswith("_"):
                continue
            out[k] = v
        if record.exc_info:
            # 异常链整段进 exc：只记 str(e) 的老写法把真因丢了，
            # 这正是"print 只能看不能查"最要命的地方。
            out["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            out["stack"] = record.stack_info
        return json.dumps(out, ensure_ascii=False, default=str)


def level_from_env(default: str = "INFO") -> int:
    """VIDEOGEN_LOG_LEVEL -> logging 级别。写错不炸，回落 default。"""
    raw = (os.environ.get("VIDEOGEN_LOG_LEVEL") or default).strip().upper()
    got = getattr(logging, raw, None)
    return got if isinstance(got, int) else logging.INFO


def configure(level: int | None = None, stream=None) -> logging.Logger:
    """挂上 JSON handler（幂等）。

    幂等是关键：`main()` 调一次、测试再调一次换个输出流 —— 不幂等的话
    一条日志会被打两遍，而"日志翻倍"这种事没人会去查，只会默默烦人。
    """
    root = logging.getLogger()
    lvl = level if isinstance(level, int) else level_from_env()
    mine = [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]
    if mine:
        h = mine[0]
        for extra in mine[1:]:
            root.removeHandler(extra)
        # 换输出流要改在同一个 handler 上，而不是再挂一个 —— 挂第二个就是
        # "一条日志打两遍"，而日志翻倍没人会去查，只会默默烦人。
        if stream is not None and isinstance(h, logging.StreamHandler):
            h.setStream(stream)
        h.setFormatter(JsonFormatter())
        h.setLevel(lvl)
        root.setLevel(lvl)
        return root
    h = logging.StreamHandler(stream or sys.stdout)
    setattr(h, _HANDLER_TAG, True)
    h.setFormatter(JsonFormatter())
    h.setLevel(lvl)
    root.addHandler(h)
    root.setLevel(lvl)
    return root


def capture() -> tuple[logging.Handler, list[str]]:
    """测试用：给 videogen.* 挂一个收日志的 handler，返回 (handler, 行列表)。

    挂在 `videogen` 上而不是 root 上，这样测到的正是**本项目打的日志**，
    不会把 pytest / httpx 自己的唠叨也算进来。
    """
    lines: list[str] = []

    class _Sink(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                lines.append(self.format(record))
            except Exception:  # noqa: BLE001 - 收日志的绝不能把被测代码弄崩
                pass

    h = _Sink()
    h.setFormatter(JsonFormatter())
    lg = logging.getLogger("videogen")
    lg.addHandler(h)
    # 把旧级别挂在 handler 上带出去：release() 必须还原，否则一个测试把
    # 级别改成 DEBUG 之后没人收回去，后面的测试会莫名多出一堆日志。
    h._saved_level = lg.level  # noqa: SLF001 - 自家类，跨函数传状态
    lg.setLevel(logging.DEBUG)              # 别把 DEBUG 挡在门外
    return h, lines


def release(handler: logging.Handler) -> None:
    lg = logging.getLogger("videogen")
    lg.removeHandler(handler)
    saved = getattr(handler, "_saved_level", logging.NOTSET)
    lg.setLevel(saved if isinstance(saved, int) else logging.NOTSET)
