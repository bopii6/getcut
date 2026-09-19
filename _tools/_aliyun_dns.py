# -*- coding: utf-8 -*-
"""阿里云 DNS 控制台代操作工具（连本机受控 Chrome 的 CDP，端口 9222）

用法：
    python _tools/_aliyun_dns.py status     # 打开/复用 DNS 控制台 tab，打印登录状态并截图
    python _tools/_aliyun_dns.py eval "expr"  # 在当前 DNS tab 执行 JS
    python _tools/_aliyun_dns.py shot out.png
"""
import base64
import json
import sys
import time

import requests
import websocket

CDP = "http://127.0.0.1:9222"
DNS_URL = "https://dns.console.aliyun.com/"


def all_tabs():
    return requests.get(f"{CDP}/json/list", timeout=10).json()


def new_tab(url="about:blank"):
    return requests.put(f"{CDP}/json/new?{url}", timeout=15).json()


class Tab:
    def __init__(self, ws_url):
        # suppress_origin：Chrome CDP 会拒绝带 Origin 头的握手
        self.ws = websocket.create_connection(
            ws_url, timeout=60, suppress_origin=True,
            http_proxy_host=None, http_proxy_port=None,
        )
        self.n = 0

    def cmd(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.n:
                return msg

    def js(self, expr):
        r = self.cmd("Runtime.evaluate", expression=expr,
                     returnByValue=True, awaitPromise=True)
        res = r.get("result", {})
        if "exceptionDetails" in res:
            return {"__error__": str(res["exceptionDetails"])[:400]}
        return res.get("result", {}).get("value")

    def nav(self, url, wait=6):
        self.cmd("Page.navigate", url=url)
        time.sleep(wait)

    def shot(self, path):
        r = self.cmd("Page.captureScreenshot", format="png")
        with open(path, "wb") as f:
            f.write(base64.b64decode(r["result"]["data"]))
        print("截图已保存:", path)
        return path


def dns_tab(reuse=True):
    """复用（或新建）DNS 控制台的 tab"""
    if reuse:
        for t in all_tabs():
            if t.get("type") == "page" and "dns.console.aliyun.com" in (t.get("url") or ""):
                return Tab(t["webSocketDebuggerUrl"])
    t = new_tab(DNS_URL)
    time.sleep(6)
    return Tab(t["webSocketDebuggerUrl"])


def status(shot_path=None):
    tab = dns_tab()
    time.sleep(3)
    url = tab.js("location.href")
    title = tab.js("document.title")
    body = tab.js("document.body ? document.body.innerText.slice(0,600) : ''")
    print("URL  :", url)
    print("TITLE:", title)
    print("BODY :", (body or "").replace("\n", " | ")[:600])
    if shot_path:
        tab.shot(shot_path)
    return tab


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status(sys.argv[2] if len(sys.argv) > 2 else None)
    elif cmd == "eval":
        tab = dns_tab()
        print(json.dumps(tab.js(sys.argv[2]), ensure_ascii=False))
    elif cmd == "shot":
        tab = dns_tab()
        tab.shot(sys.argv[2])
