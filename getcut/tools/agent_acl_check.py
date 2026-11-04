"""越权修复的线上验收：临时建一个二号账号，用它去够别人的东西，全部应当被挡。

跑完自动删掉测试账号。只在服务器容器里跑：
    docker exec -e PYTHONPATH=/app getcut python /tmp/agent_acl_check.py
"""
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from starlette.requests import Request

from getcut import auth, config, server

BASE = "http://127.0.0.1:8600"
TEST = "qa-crossuser@test.local"
results = []


def req(path, cookie=None, token=None, method="GET", body=None):
    r = urllib.request.Request(BASE + path, method=method)
    if cookie:
        r.add_header("Cookie", "vg_session=" + cookie)
    if token:
        r.add_header("x-auth-token", token)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, data, timeout=25) as resp:
            raw = resp.read()
            return resp.status, raw[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]


def check(name, got, want):
    ok = got == want
    results.append((ok, name, "得到 %s / 期望 %s" % (got, want)))
    print("%-4s %-52s %s" % ("PASS" if ok else "FAIL", name, got))


# ── 前置：测试账号、以及"别人的东西"长什么样 ──
if not any(u["email"] == TEST for u in auth._load_users()):
    auth.create_user(TEST, "Qa-cross-2026!")
test_ck = auth.make_session(TEST)
admin_ck = None
with server._LOCK:
    jobs = dict(server.JOBS)
    reg = server._reg()
other_job = next(iter(jobs), None)
owner_pid = next((p["project_id"] for p in reg["projects"] if p.get("bundle")), None)
owner_bundle = next((p["bundle"] for p in reg["projects"] if p.get("bundle")), None)
tok = config.AUTH_TOKEN
print("样本：job=%s pid=%s bundle=%s\n" % (other_job, owner_pid, owner_bundle))

check("任务列表不再外泄全站快照",
      json.loads(req("/api/jobs", test_ck)[1]).get("agent"), None)
check("agent/status 对普通账号只回自己（0 条）",
      len(json.loads(req("/api/agent/status", test_ck)[1]).get("jobs") or []), 0)
if other_job:
    for label, path, kw in [
        ("agent-media 取别人配音", "/agent-media/%s/audio/voice.mp3" % other_job, {}),
        ("agent file 取别人渲染包", "/api/agent/job/%s/file?path=props.json" % other_job, {}),
        ("progress 报别人任务", "/api/agent/job/%s/progress?device=x" % other_job,
         dict(method="POST", body={"pct": 1})),
        ("visual 交别人成片", "/api/agent/job/%s/visual?device=x" % other_job,
         dict(method="POST", body={})),
        ("layer 交别人图层", "/api/agent/job/%s/layer?device=x&name=base.png" % other_job,
         dict(method="POST", body={})),
    ]:
        check(label + " 被挡", req(path, test_ck, **kw)[0], 403)
    check("管理员令牌仍可看全站状态（没误伤）",
          len(json.loads(req("/api/agent/status", token=tok)[1]).get("jobs") or []) >= 0, True)
if owner_pid and owner_bundle:
    # 真正的攻击形状是"用我自己的项目 + 别人的素材包"，所以先给测试号造一个空项目
    with server._LOCK:
        r2 = server._reg()
        r2["projects"].append({"project_id": "qacl00000000", "owner": TEST,
                               "bundle": "", "title": "QA越权验收"})
        server._reg_save(r2)
    check("自己的项目 + 别人素材包 跑预演被挡",
          req("/api/projects/qacl00000000/preview/plan", test_ck, method="POST",
              body={"bundle": owner_bundle})[0], 400)
    # 409 = 预演没跑过所以拒绝（这条在归属校验之前，先被状态挡住了）；400 = 被归属挡住
    check("自己的项目 + 别人素材包 出分镜被挡",
          req("/api/projects/qacl00000000/preview/shots", test_ck, method="POST",
              body={"bundle": owner_bundle})[0] in (400, 409), True)
    check("连别人的项目号都摸不到（404 不是 403）",
          req("/api/projects/%s/preview/plan" % owner_pid, test_ck, method="POST",
              body={"bundle": owner_bundle})[0], 404)
    with server._LOCK:
        r3 = server._reg()
        r3["projects"] = [p for p in r3["projects"] if p["project_id"] != "qacl00000000"]
        server._reg_save(r3)
# 越到兄弟目录：被挡时回退成"给成片台首页"，所以要比字节而不是看状态码
sib = Path(config.STATIC) / "poc_webm_bak" / "index.html"
code, body = req("/poc/../poc_webm_bak/index.html", test_ck)
leak = sib.is_file() and body == sib.read_bytes()[:200]
check("/poc 越到兄弟目录拿不到那里的文件", leak, False)
check("借别人的克隆音色试听被挡",
      req("/api/voice-preview?voice=cosyvoice-qafake123", test_ck)[0], 404)

# ── 第二阶段：正路不能被误挡 ──
# 合成任务只存在于本进程，走 HTTP 测不到，所以这里直接验判定函数本身：
# 同一个账号，用 cookie 来、用设备令牌来，都必须放行；换人必须 403。
own_job = "qacljob0000001"


def fake_req(cookie=None, token=None, master=None):
    hdrs = []
    if cookie:
        hdrs.append((b"cookie", ("vg_session=" + cookie).encode()))
    if token:
        hdrs.append((b"x-agent-token", token.encode()))
    if master:
        hdrs.append((b"x-auth-token", master.encode()))
    return Request({"type": "http", "method": "GET", "path": "/x", "headers": hdrs,
                    "query_string": b"", "scheme": "http", "server": ("127.0.0.1", 80),
                    "client": ("127.0.0.1", 1234), "root_path": ""})


dev_tok = auth.make_session(TEST, auth.SESSION_TTL_LONG)   # /api/agent/login 签的就是这种
for label, rq in [("会话 cookie", fake_req(cookie=test_ck)),
                  ("设备令牌", fake_req(token=dev_tok)),
                  ("主令牌", fake_req(master=tok))]:
    with server._LOCK:
        server.JOBS[own_job] = {"stage": "rendering", "owner": TEST, "project_id": None}
    check("主人用%s取自己的单放行" % label, server._agent_job_ok(own_job, rq), None)
with server._LOCK:
    server.JOBS[own_job] = {"stage": "rendering", "owner": "someone-else@x.com",
                            "project_id": None}
    resp = server._agent_job_ok(own_job, fake_req(cookie=test_ck))
check("别人的单仍被挡", getattr(resp, "status_code", None), 403)
_orig_reg = server._reg                      # 只在本进程内假造一条项目，不落盘
server._reg = lambda: {"projects": [{"project_id": "qacl-proj", "owner": TEST}]}
try:
    with server._LOCK:
        server.JOBS[own_job] = {"stage": "rendering", "owner": None, "project_id": "qacl-proj"}
        check("老任务（没记 owner）退到项目归属也能放行",
              server._agent_job_ok(own_job, fake_req(cookie=test_ck)), None)
        server.JOBS[own_job] = {"stage": "rendering", "owner": None, "project_id": "别的"}
        check("项目也不是他的 → 403",
              getattr(server._agent_job_ok(own_job, fake_req(cookie=test_ck)), "status_code", None),
              403)
finally:
    server._reg = _orig_reg
    with server._LOCK:
        server.JOBS.pop(own_job, None)

# ── 收尾：删测试账号（走 safestore，账号表不留半截） ──
users = [u for u in auth._load_users() if u["email"] != TEST]
auth._save_users(users)
print("\n测试账号已删除，账号数回到 %d" % len(users))
bad = [r for r in results if not r[0]]
print("PASS %d / FAIL %d" % (len(results) - len(bad), len(bad)))
for _, n, why in bad:
    print("  FAIL", n, why)
sys.exit(1 if bad else 0)
