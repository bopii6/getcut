"""三页法定文本：隐私政策 / 用户协议 / 退款说明。

为什么要单独一个模块：这三页的每一个数字都必须和代码里真实做的事对上。
写"用完即删"而代码留着文件，或者写"30 天清理"而清理任务是 90 天，
将来被投诉时这些句子就是证据 —— 所以留存期常量放在这里，由清理与注销逻辑引用，
不允许两边各写一份。

口径来源（站长 2026-09-21 拍板）：
  · 一次性买断，**不支持退款**（唯一例外写进退款页，是我们主动承担的那句）
  · 客户的原始录音**不在服务器留档**（声音复刻登记完即删，见 brand.set_clone）
  · 管理员只有站长一人，由 `VIDEOGEN_ADMIN_EMAILS` 白名单决定
"""
from __future__ import annotations

import time

# ── 留存期（天）：三页文案与清理/注销逻辑共用这一份，别在别处硬写数字 ──
RETENTION = {
    "bundle_days": 90,        # 素材包与成片：最后一次使用后保留 90 天
    "log_days": 30,           # 服务器访问与任务日志
    "license_days": 3 * 365,  # 卡密与购买记录（财务留痕，注销后仍保留但去身份）
    "backup_days": 90,        # 每日状态备份滚动保留 90 天
    "erase_after_days": 30,   # 注销后多久把主数据清干净
}

CONTACT_NOTE = "首页右上角「怎么用」页里有站长的微信，任何一条你不认可都可以直接提出来"

_UPDATED = "2026 年 9 月 21 日"

_CSS = """
:root{--bg:#0d0b14;--surface:#171422;--surface2:#211d31;--ink:#efecf6;--ink-2:#a79fbd;
--ink-3:#8c85a3;--line:#2e2942;--acc:#cbb88a;--r:10px;
--sans:"PingFang SC","HarmonyOS Sans SC","MiSans","Microsoft YaHei UI","Microsoft YaHei",system-ui,sans-serif}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font-family:var(--sans);line-height:1.85;-webkit-font-smoothing:antialiased}
.wrap{max-width:760px;margin:0 auto;padding:40px 22px 80px}
nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:26px}
nav a{color:var(--ink-2);text-decoration:none;border:1px solid var(--line);
border-radius:999px;padding:5px 14px;font-size:13.5px}
nav a[aria-current]{color:var(--acc);border-color:var(--acc)}
h1{font-size:30px;line-height:1.3;margin:0 0 6px;letter-spacing:.01em}
.upd{color:var(--ink-3);font-size:13px;margin:0 0 30px}
h2{font-size:19px;margin:34px 0 10px;color:var(--acc);letter-spacing:.02em}
p,li{font-size:15.5px;color:var(--ink)}
ul{padding-left:22px;margin:8px 0}
.card{background:var(--surface);border:1px solid var(--line);border-radius:var(--r);
padding:18px 20px;margin:16px 0}
.big{font-size:17px;font-weight:700}
table{width:100%;border-collapse:collapse;margin:12px 0;font-size:14.5px}
th,td{border-bottom:1px solid var(--line);padding:9px 8px;text-align:left;vertical-align:top}
th{color:var(--ink-3);font-weight:700;font-size:13px}
a{color:var(--acc)}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--line);
color:var(--ink-3);font-size:13.5px}
@media (prefers-reduced-motion: no-preference){a,nav a{transition:border-color .18s,color .18s}}
"""


def _nav(current: str) -> str:
    items = [("privacy", "隐私政策"), ("terms", "用户协议"), ("refund", "退款说明")]
    links = "".join(f'<a href="/{k}"' + (' aria-current="page"' if k == current else "")
                    + f">{n}</a>" for k, n in items)
    return f'<nav aria-label="条款页之间切换">{links}<a href="/">回成片台</a></nav>'


_PRIVACY = f"""
<h2>我们收集什么、为什么不收集别的</h2>
<ul>
<li><b>必需</b>：登录邮箱、昵称与头像（你自己可改）、你上传的素材包（文案、图片、视频）、
生成出来的成片文件、品牌套装（你的 logo、术语表、水印文字）。</li>
<li><b>声音复刻</b>：你录的那段原始音频<b>不在服务器留档</b>。它只用于向语音服务登记一次，
登记完成即随临时目录删除，服务器上不保存副本。之后你听到的"试听"是我们用合成音重新生成的，
不是你的原声录音。</li>
<li><b>不收集</b>：手机号、身份证、通讯录、位置、设备广告标识。我们不接入任何广告或统计跟踪脚本，
页面里没有第三方 cookie。</li>
</ul>

<h2>Cookie 只有三个，都为了让你能用</h2>
<table><tr><th>名称</th><th>作用</th><th>活多久</th></tr>
<tr><td>vg_session</td><td>登录通行证，让你不必每次输密码</td><td>7 天；勾选"记住我"30 天</td></tr>
<tr><td>vg_try</td><td>免费试做的次数计数（不用于任何画像或广告）</td><td>180 天</td></tr>
<tr><td>localStorage</td><td>你上本机的界面偏好（配色、上次用的模板）</td><td>你自己清</td></tr></table>

<h2>数据放在哪、谁能看到</h2>
<ul>
<li>服务器与全部数据都在<b>腾讯云中国境内</b>的同一台机器上；成片另有存放在腾讯云对象存储（COS）。</li>
<li>账号、素材包、成片都按归属隔离：你只能看到自己的；普通用户之间互相看不到。</li>
<li>站长（唯一管理员）在处理故障时可以看到任务状态与成片列表。除为你排障、以及法律要求之外，
不会用于任何其他用途，也不会出售或对外提供。</li>
</ul>

<h2>保留多久（这一条与代码里的清理逻辑一致）</h2>
<table><tr><th>内容</th><th>保留</th></tr>
<tr><td>素材包与成片</td><td>最后一次使用后 {RETENTION['bundle_days']} 天内保留，之后清理</td></tr>
<tr><td>服务器访问与任务日志</td><td>{RETENTION['log_days']} 天</td></tr>
<tr><td>账号资料</td><td>直到你注销</td></tr>
<tr><td>卡密与购买记录</td><td>{RETENTION['license_days'] // 365} 年（财务留痕；注销后这层记录会去掉你的邮箱）</td></tr>
<tr><td>每日状态备份</td><td>滚动 {RETENTION['backup_days']} 天</td></tr></table>
<p>你注销后，主数据在 <b>{RETENTION['erase_after_days']} 天内</b>清除；
备份里的那份随滚动周期在最长 <b>{RETENTION['backup_days']} 天内</b>自然消失。
我们把这段窗口写出来，是因为说"立即彻底删除"而实际做不到，比不写更糟。</p>

<h2>会用到哪些第三方服务</h2>
<ul>
<li>大模型（写稿与分镜）：DeepSeek、智谱 AI；</li>
<li>配音与声音复刻：阿里云百炼；</li>
<li>免版权图库与视频：Pexels、Pixabay（遵循其各自的许可条款）；</li>
<li>服务器与对象存储：腾讯云。</li>
</ul>
<p>提交内容时，为完成生成，相关内容会传给上述服务处理。它们只处理你这一次请求所需的部分。</p>

<h2>你的权利</h2>
<ul>
<li>随时在「我的」里更正昵称、头像、品牌套装，或导出你的成片；</li>
<li>随时注销账号：设置 → 我的 → 注销账号，输入密码确认即可，
我们会删掉你的素材包、成片、品牌套装与克隆音色登记，并让所有已登录设备立刻失效；</li>
<li>要求我们提供、更正或删除你的个人信息，{CONTACT_NOTE}。</li>
</ul>

<h2>未成年人</h2>
<p>本服务面向成年创作者。若你是未满 18 岁的用户，请在监护人同意与陪同下使用。</p>
"""

_TERMS = f"""
<h2>你买的是什么</h2>
<p>GetCut（videogen）是一次性买断的短视频生成工具：你把素材包拖进成片台，
文案配音、分镜、画面渲染与混音<b>在你自己的电脑浏览器里完成</b>，产出一条可直接发布的竖屏成片。
服务器负责选题整理、账号与卡密、素材与成片的存放。</p>
<ul>
<li><b>永久基础版 ¥399</b>：不限次生成、720p/1080p 出片、免版税音效库。</li>
<li><b>永久高级版 ¥599</b>：以上全部 + 剪映草稿导出 + 品牌套装（logo / 术语表 / 水印）+
声音复刻 + 优先排队。</li>
</ul>
<p>「永久」指我们持续提供该服务的整个运营期内不再另行收费；不承诺服务永久存在（见"服务变更"）。</p>

<h2>账号规则</h2>
<ul>
<li>一个账号供一个人使用。不要把账号、卡密、成片链接转卖或共享给他人经营。</li>
<li>卡密一经核销即绑定该账号，不可换绑；填错可以联系我们处理。</li>
<li>本服务<b>一次性买断、付款后不支持退款</b>（唯一例外见<a href="/refund">退款说明</a>：
因我方原因连续 7 天以上无法出片且修不好）。</li>
<li>你需对账号下的全部行为负责，包括别人用你的登录状态做的事。</li>
</ul>

<h2>内容责任（重要）</h2>
<ul>
<li>你上传的文案、图片、视频与生成的成片，权利与责任归你。请确保你有权使用其中的素材、
音乐与肖像。</li>
<li>AI 生成的文案与数字<b>必须由你自行核实后再发布</b>。工具会尽力标注来源，
但不构成事实核验服务；因未经核实发布造成的后果由发布者承担。</li>
<li>不得用于违法、侵权、虚假宣传、冒充他人、色情与暴力等违反法律与平台规则的内容。
我们发现此类使用有权停止服务。</li>
</ul>

<h2>服务变更、故障与终止</h2>
<ul>
<li>我们会持续改进功能，可能调整界面与参数；重大能力下线会提前在页面公告。</li>
<li>服务按"现状"提供。出现无法出片的故障时请优先联系我们 —— 我们承诺在能修好的前提下修好；
若因我方原因长时间无法提供核心出片能力，见退款说明中的例外条款。</li>
<li>你可以随时停止使用并注销账号；我们若终止运营，会提前在首页公告并保留你导出成片的窗口。</li>
</ul>

<h2>其他</h2>
<ul>
<li>本服务面向中国大陆用户，适用中华人民共和国法律。</li>
<li>政策与协议更新后会在本页公布并更新日期；继续使用视为接受。
有争议时，{CONTACT_NOTE}。</li>
</ul>
"""

_REFUND = f"""
<div class="card big">本产品为一次性买断的软件服务，<b>购买后不支持退款</b>。</div>

<h2>为什么这样定</h2>
<p>软件一旦交付即可无限使用，退款规则如果留口子，被复制走功能再退回来是必然结果，
最终受伤的是老老实实付费的用户。所以这条对所有人生效，包括我们自己不想讲人情。</p>

<h2>唯一例外：我们这边的问题</h2>
<p>如果出现下面这种情况，<b>联系我们，我们会退</b>：因我方原因导致你<b>连续 7 天以上无法出片</b>，
而我们没能修好。退款按剩余可用时间比例计算（买断无期限时按你实际可用的天数比例，
双方协商确定）。这条不是给你留的退路，是我们给自己上的枷锁 —— 写在这里，你可以拿它来要求我们。</p>

<h2>买之前先确认这两件事</h2>
<ul>
<li>出片在<b>你自己的电脑</b>上完成：需要新版 Chrome 或 Edge。5 年以上的老机器会慢一些。</li>
<li>先用免费试玩：选一个选题，一条十几秒带水印的样片，看完再决定。</li>
</ul>

<h2>换卡密、买错档位</h2>
<ul>
<li>卡密填错、买错档位（基础买成高级或相反）：可以联系我们换绑或补差价，
这类我们照办，不收手续费。</li>
<li>账号丢失（邮箱换号、密码忘了）：用「忘记密码」走邮箱验证码找回；
如果注册邮箱已不可用，{CONTACT_NOTE}，我们会核对购买凭证后帮你迁移。</li>
</ul>

<h2>怎么联系</h2>
<p>首页右上角「怎么用」里有站长微信；付款凭证（微信/支付宝账单截图）保留一下，
换绑和迁移都要用它核对。</p>
"""

PAGES = {"privacy": ("隐私政策", _PRIVACY), "terms": ("用户协议", _TERMS),
         "refund": ("退款说明", _REFUND)}


def page(kind: str) -> str:
    """返回整页 HTML。kind 不在表里时返回空串，由调用方给 404。"""
    if kind not in PAGES:
        return ""
    title, body = PAGES[kind]
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · GetCut 成片台</title>
<meta name="description" content="GetCut（videogen）{title}：收集什么、留多久、能不能退。">
<meta name="robots" content="index,follow">
<style>{_CSS}</style></head><body><div class="wrap">
{_nav(kind)}
<h1>{title}</h1>
<p class="upd">更新日期：{_UPDATED}　·　生效日期：{_UPDATED}</p>
{body}
<footer>GetCut · videogen　服务器与数据位于腾讯云中国境内　·　
本页与产品实际行为逐条对齐，发现不一致请以更对你有利的那条为准，并告诉我们。</footer>
</div></body></html>"""


def retention_summary() -> dict:
    """给清理/注销逻辑引用的同一份数字（避免代码与文案各写一套）。"""
    out = dict(RETENTION)
    out["erase_deadline"] = time.time() + out["erase_after_days"] * 86400
    return out
