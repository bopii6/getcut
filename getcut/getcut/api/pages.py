"""页面与健康检查（/、/studio、/i 短链、/healthz、/api/version）。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

from fastapi import Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from .. import version

from .. import ctx

from fastapi import APIRouter

router = APIRouter()

@router.get("/", response_class=HTMLResponse)
def index(request: Request) -> Response:
    """首页就是成片台本体：拖包 → 生成 → 取片一屏走完，不必先进工作台找入口。
    静态资源仍在 /poc/ 下，靠 <base> 让页面里的相对路径照旧解析。"""
    page = ctx._poc_html()
    if isinstance(page, JSONResponse):
        return page
    return ctx._page(request, page.replace("<head>", '<head><base href="/poc/">', 1))
@router.get("/studio", response_class=Response)
@router.get("/studio/", response_class=Response)
def studio(request: Request) -> Response:
    """工作台已下线（2026-09-23 用户拍板：整个产品只留成片台一个页面）。

    老书签/旧链接 302 送回成片台；历史版本与剪映草稿由成片台页内的
    「导入剪映（分轨草稿）」与作品库承接，不再有独立页面。
    """
    return RedirectResponse("/", status_code=302)
@router.get("/i/{code}", response_class=HTMLResponse)
def intake_page(code: str, request: Request) -> Response:
    """Agent 直投短链：与 / 同一份 SPA，前端按路径进入「素材包已送达」落地页。"""
    return ctx._page(request, _inject_browser_export((ctx.STATIC / "index.html").read_text(encoding="utf-8")))
# 成片台悬浮组件：有任务在等成片台时，任务页右下角浮出按钮，
# 点击全屏打开 /poc/ 成片台（纯浏览器渲染合成），完成后 postMessage 通知收起。
_BROWSER_EXPORT_WIDGET = """
<script>
(function(){
  if (window.__gcExportWidget) return; window.__gcExportWidget = 1;
  var wrap = null;
  function waitingCount(){
    return fetch('/api/jobs', {credentials:'same-origin'})
      .then(function(r){ return r.json(); })
      .then(function(d){
        var a = (d && d.active) || [];
        return a.filter(function(j){
          return j.stage === 'render' && /等待成片台/.test(j.detail || '');
        }).length;
      }).catch(function(){ return 0; });
  }
  function show(n){
    if (!wrap){
      wrap = document.createElement('div');
      wrap.style.cssText = 'position:fixed;inset:0;z-index:2147483000;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;';
      var b = document.createElement('button');
      b.id = 'gc-bx-go';
      b.style.cssText = 'all:unset;cursor:pointer;background:var(--acc);color:var(--acc-ink);padding:16px 30px;border-radius:9px;font:700 18px/1.45 var(--sans);text-align:center;box-shadow:var(--sh-2);';
      b.addEventListener('click', openFrame);
      wrap.appendChild(b);
      document.body.appendChild(wrap);
    }
    wrap.firstChild.innerHTML = '有 ' + n + ' 条视频等你生成<br><span style=\"font-size:14px;font-weight:400;opacity:.85\">点击在你这台电脑上完成，直接出带声 MP4（每条约 1~4 分钟，期间保持本页打开）</span>';
    wrap.style.display = 'flex';
  }
  function openFrame(){
    var f = document.getElementById('gc-bx-frame');
    if (f) return;
    f = document.createElement('iframe');
    f.id = 'gc-bx-frame';
    f.src = '/poc/?agent=1&device=' + encodeURIComponent('\\u7f51\\u9875\\u6d4f\\u89c8\\u5668');
    f.allow = 'display-capture';
    f.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;border:0;z-index:2147483001;background:#111;';
    document.body.appendChild(f);
    // 手机上这一层是全屏 iframe，原来只在渲染完成时才移除 —— 领不到单的手机，
    // 点进来就是死路。给一个常驻出口。
    var x = document.createElement('button');
    x.id = 'gc-bx-close';
    x.type = 'button';
    x.textContent = '退出';
    x.style.cssText = 'position:fixed;top:12px;right:12px;z-index:2147483002;padding:9px 16px;border-radius:999px;border:0;background:rgba(0,0,0,.66);color:#fff;font:600 14px/1.2 system-ui,sans-serif;cursor:pointer;';
    x.addEventListener('click', function(){ f.remove(); x.remove(); });
    document.body.appendChild(x);
    window.addEventListener('message', function(ev){
      if (ev.data && ev.data.type === 'getcut-export-done' && f.parentNode){
        setTimeout(function(){ f.remove(); x.remove(); location.reload(); }, 1800);
      }
    });
  }
  function isMobile(){
    return /Android|iPhone|iPad|iPod|Mobile|HarmonyOS/i.test(navigator.userAgent || '');
  }
  function tick(){
    waitingCount().then(function(n){
      // 手机领不到渲染单（成片台在手机上不轮询），自动全屏只会把人困住：
      // 桌面上照旧自动弹，手机上只保留顶部按钮，由用户自己点。
      if (n > 0 && !isMobile()) openFrame();
    });
  }
  function boot(){ tick(); setInterval(tick, 5000); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
</script>"""
def _inject_browser_export(html: str) -> str:
    if "</body>" in html and "__gcExportWidget" not in html:
        return html.replace("</body>", _BROWSER_EXPORT_WIDGET + "</body>", 1)
    return html
@router.get("/healthz")
def healthz():
    """云平台健康检查（不落盘、不触发扫描副作用）。

    这里**不再报版本号**：以前硬编码 `"version": "1.0"`，说了等于没说；
    真版本在 `/api/version`（要登录），不把精确版本暴露给匿名探针。
    """
    return {"ok": True, "jobs": len(ctx.JOBS)}
@router.get("/api/version")
def api_version():
    """线上到底是哪一版：commit + 构建时间 + 关键依赖的实际版本。

    故意留在鉴权后面（不进 _PUBLIC_PATHS）：匿名访问者不该拿到精确版本信息，
    而问这个问题的站长/排障本来就登录着；外部只需要 /healthz 那个存活信号。
    读的是**运行时真实装着的**版本，不是 requirements 里写的期望值 ——
    生产是宿主绑挂代码 + 部署时还会 pip 装包，只有问运行时才算数。
    """
    from importlib import metadata as md
    deps = {}
    for name in ("fastapi", "starlette", "pydantic", "pillow", "websockets",
                 "cos-python-sdk-v5", "edge-tts", "requests", "python-multipart"):
        try:
            deps[name] = md.version(name)
        except Exception:  # noqa: BLE001 - 装没装都要说实话
            deps[name] = "未安装"
    return {**version.info(), "deps": deps}
