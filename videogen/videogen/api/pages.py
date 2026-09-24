"""页面与健康检查（/、/studio、/i 短链、/healthz、/api/version）。

从 server.py 按域拆出来的路由。
路由**注册顺序**由 server 里的 include_router 顺序决定（按各域首条路由行号
排序），改动顺序前先看 tests/test_route_order.py 的检查 —— 顺序反了会被通配路由吃掉。
"""
from __future__ import annotations

from html import escape

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
@router.get("/agent/authorize", response_class=HTMLResponse)
def agent_authorize_page(request: Request, request_id: str = "") -> Response:
    """客户可见的 Agent 授权页：只确认账号，不展示令牌。"""
    rid = escape(str(request_id or ""), quote=True)
    return HTMLResponse(f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>授权电脑 Agent · GetCut</title>
<style>
*{{box-sizing:border-box}} body{{margin:0;background:#f5f5f7;color:#16181d;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
main{{max-width:460px;margin:9vh auto;padding:0 18px}} .card{{background:#fff;border:1px solid #e3e5e9;border-radius:16px;padding:28px;box-shadow:0 16px 50px #00000012}}
h1{{font-size:23px;margin:0 0 8px}} p{{color:#626873;margin:8px 0 20px}} .account{{background:#f5f5f7;border-radius:10px;padding:13px;margin:18px 0}}
button,a{{font:inherit}} button{{width:100%;border:0;border-radius:10px;padding:13px 18px;background:#6d43d6;color:#fff;font-weight:700;cursor:pointer}} a{{display:block;text-align:center;color:#6d43d6;text-decoration:none;margin-top:12px;padding:10px}}
#msg{{min-height:24px;color:#626873;margin-top:16px}} .ok{{color:#16845b}} .err{{color:#c33}}
</style></head><body><main><div class="card">
<h1>授权电脑 Agent</h1>
<p>确认后，这台电脑上的 Agent 才能把素材包上传到你的 GetCut 账号。</p>
<div id="device" class="account">正在读取设备信息…</div>
<button id="approve" disabled>授权这台电脑</button>
<a href="/">返回 GetCut 登录或注册</a>
<div id="msg"></div>
</div></main><script>
const rid={rid!r}; const $=id=>document.getElementById(id); let ready=false;
async function boot(){{
  if(!rid){{$('device').textContent='授权链接无效';return;}}
  let info=await fetch('/api/agent/authorize/info?request_id='+encodeURIComponent(rid),{{credentials:'same-origin'}}).then(r=>r.json());
  if(info.error||$('device')===null){{$('device').textContent=info.error||'授权链接无效';return;}}
  $('device').textContent='要授权的设备：'+(info.device||'电脑 Agent')+' · 请求 '+(info.user_code||'');
  if(info.status!=='pending'){{$('msg').textContent=info.status==='approved'?'这台电脑已经授权过了。':info.status==='expired'?'授权链接已过期，请回到 Agent 重新发起。':'授权请求已结束。';return;}}
  let me=await fetch('/api/me',{{credentials:'same-origin'}}).then(r=>r.ok?r.json():null);
  if(!me){{$('device').textContent='当前浏览器还没有登录 GetCut。请先登录或注册，再重新打开这个授权链接。';return;}}
  $('device').innerHTML='当前账号：<b>'+me.email+'</b><br>要授权的设备：'+(info.device||'电脑 Agent');
  ready=true; $('approve').disabled=false;
}}
$('approve').onclick=async()=>{{
  if(!ready)return; $('approve').disabled=true; $('msg').textContent='正在授权…';
  let r=await fetch('/api/agent/authorize/approve',{{method:'POST',headers:{{'content-type':'application/json'}},credentials:'same-origin',body:JSON.stringify({{request_id:rid}})}});
  let d=await r.json().catch(()=>({{}}));
  if(r.ok){{$('msg').className='ok';$('msg').textContent='已授权，电脑 Agent 现在可以使用这个账号。回到 Agent 继续即可。';}}
  else{{$('msg').className='err';$('msg').textContent=d.error||'授权失败';$('approve').disabled=false;}}
}};
boot();
</script></body></html>""")


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
    window.addEventListener('message', function(ev){
      if (ev.data && ev.data.type === 'getcut-export-done' && f.parentNode){
        setTimeout(function(){ f.remove(); location.reload(); }, 1800);
      }
    });
  }
  function tick(){
    waitingCount().then(function(n){
      if (n > 0) openFrame();
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
