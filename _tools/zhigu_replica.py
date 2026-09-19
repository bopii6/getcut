# -*- coding: utf-8 -*-
"""智谷三段式 1:1 复刻构建器：按参考片时间轴逐拍建 props → TTS → 渲染 → 混音。
用法： cd videogen && python ../_tools/zhigu_replica.py
"""
import sys, json, shutil, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'videogen'))
from videogen.schemas import Content
from videogen import tts, compose, remotion_render as rr
from videogen.planner import align_timeline, split_clauses

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / '_replica'
WORK.mkdir(exist_ok=True)

# ---------------- 素材源（repo 相对路径） ----------------
MEDIA_SRC = {
    'robot':   'niwo-bundle-ai-pause/videos/08-robot.mp4',
    'robot2':  'niwo-bundle-ai-pause/videos/09-robot.mp4',
    'office':  'niwo-bundle-ai-pause/videos/11-office.mp4',
    'city':    'niwo-bundle-ai-pause/videos/05-city.mp4',
    'tech':    'niwo-bundle-ai-pause/videos/03-tech.mp4',
    'server':  'niwo-bundle-ai-pause/videos/14-server.mp4',
    'crowd':   'niwo-bundle-ai-pause/videos/10-crowd.mp4',
    'finance': 'niwo-bundle-ai-pause/videos/06-finance.mp4',
    'dc':      'niwo-bundle-ai-pause/videos/01-datacenter.mp4',
    'chipfab': 'niwo-bundle-ai-pause/videos/17-chipfab.mp4',
    'chip':    'AI刹车2-素材包/videos/09-chip.mp4',
    'cyber':   'AI刹车2-素材包/videos/07-cyber.mp4',
}

# ---------------- 逐拍分镜表（一句话一拍，按参考片段落顺序） ----------------
BEATS = [
    ('hook', 'robot', '最近互联网大厂，点燃了AI办公大战。',
     {'pills': ['让AI直接干活', '让一个人拥有一个团队的生产力']}),
    ('media', 'office', '腾讯全力押注，搬出了WorkBuddy。', {'chips': ['WorkBuddy']}),
    ('media', 'crowd', '字节跳动搬出全家桶，应战火力全开。',
     {'chips': ['豆包', '飞书', '扣子', 'TRAE']}),
    ('tree', None, '百度随即升级百度搭子，正面迎战。',
     {'tree': {'center': {'title': '百度搭子', 'sub': 'DuMate'},
               'children': ['个人版', '企业版', '行业套件']}}),
    ('media', 'city', '随着大厂纷纷入局，七月的AI办公赛道彻底烧了起来。', {}),
    ('table', 'dc', '第三方榜单上，腾讯和百度搭子包揽月活前二。',
     {'table': {'title': 'AI产品榜 · AI办公智能体总榜', 'rows': [
         {'name': 'WorkBuddy · 腾讯', 'value': '1115.23万', 'delta': '+304.40%', 'highlight': True},
         {'name': '百度搭子 · 百度', 'value': '674.30万', 'delta': '+1063.79%'},
         {'name': 'TraeWork · 字节', 'value': '285.99万', 'delta': '+51.08%'},
         {'name': '扣子 · 字节', 'value': '217.33万', 'delta': '+62.23%'}]}}),
    ('table', 'dc', '而百度搭子，直接焊死在增速榜第一。',
     {'table': {'title': 'AI产品榜 · AI办公智能体增速榜', 'tooltip': '百度搭子 674.30万 · +1063.79%', 'rows': [
         {'name': '百度搭子 · 百度', 'value': '674.30万', 'delta': '+1063.79%', 'highlight': True},
         {'name': 'WorkBuddy · 腾讯', 'value': '1115.23万', 'delta': '+304.40%'},
         {'name': 'TraeWork · 字节', 'value': '285.99万', 'delta': '+51.08%'},
         {'name': '扣子 · 字节', 'value': '217.33万', 'delta': '+62.23%'}]}}),
    ('number', None, '月活674.3万，环比暴涨1063.79%。',
     {'number': '1063.79%', 'label': '百度搭子 · 环比增速', 'caption': '上线 5 个月'}),
    ('chips-media', 'office', '查资料、写报告、做PPT，已经成为办公标配。',
     {'chips': ['查资料', '写报告', '做PPT']}),
    ('swap', 'robot', '行业内真正的竞争，是让AI从工具，变成智能体。',
     {'swap': {'a': {'label': '工具', 'text': '你说什么，它做什么'},
               'b': {'label': '智能体', 'text': '自己拆解任务、直接干活'}}}),
    ('hook', 'crowd', '这次发布会上，百度搭子提出了交付即惊艳。', {'pills': ['交付即惊艳']}),
    ('media', 'tech', 'AI不再是简单生成一段文字。', {}),
    ('cards3', None, '它是真的懂你的业务：能直接交付马上就能汇报的成品。',
     {'cards': [{'title': '公众号文章', 'sub': '直接可发'}, {'title': '图文笔记', 'sub': '带配图'},
                {'title': '数字人播报', 'sub': '带口播视频'}]}),
    ('swap', 'chip', 'AI办公的评价标准，已经从有没有使用，变成了活干得好不好。',
     {'swap': {'a': {'label': '有没有使用', 'text': '装个AI放那儿吃灰'},
               'b': {'label': '活干得好不好', 'text': '交付能直接用的成品'}}}),
    ('media', 'dc', '为什么百度搭子的增速这么快？', {}),
    ('chips-dark', None, '它没有泛泛堆砌办公功能，反而深入刚需场景。',
     {'title': '深入刚需场景', 'chips': ['金融', '自媒体', '教育', '设计']}),
    ('chips-dark', None, '把行业的知识、skill和工具资源，做成了专业套件。',
     {'title': '专业套件', 'chips': ['知识', 'skill', '工具资源']}),
    ('media', 'robot2', '让AI成为懂这个行业的老员工，直接上场干活。', {}),
    ('checklist', None, '比如我们实测了自媒体套件，让搭子先分析账号定位。',
     {'title': '自媒体套件 · 实测', 'items': ['分析账号定位', '每天批量筛选题', '排出优先级']}),
    ('media', 'office', '每天我们拿到AI定好优先级的选题，直接判断要不要跟进。', {}),
    ('quote', None, '之后每个选题让AI进一步研究，并且直接生成了文案和配图。',
     {'quote': '请写一份话题策划：包含文案、配图和一份可直接发布的笔记'}),
    ('media', 'finance', '更专业的金融场景，我们让百度搭子分析科技公司的财报。', {}),
    ('quote', None, '只用了十几分钟，就给出了这样一份研报。',
     {'quote': '美股科技巨头Q2财报与AI投入分析：自动完成公司分类，并从权威来源汇总数据'}),
    ('media', 'server', '各大公司的AI商业化进程和市场表现分化，也分析得明明白白。', {}),
    ('brand', None, '这就是百度搭子快速增长的原因。', {'name': 'DuMate', 'sub': '百度搭子'}),
    ('media', 'cyber', '它改变了AI和人的分工：过去最耗时间的任务都交给AI。', {}),
    ('media', 'office', '人只负责判断质量、提出意见。', {'chips': ['搜资料', '跑数据', '做研究']}),
    ('person', None, '雪服品牌创始人栗噔噔，用搭子辅助做自媒体，一个人就能搞定。',
     {'person': {'name': '栗噔噔', 'caption': '前腾讯产品经理 · AI科技博主',
                 'chips': ['选题策划', '创作', '运营', '平台分发']}}),
    ('person', None, '90后缝纫教父吕杭，用搭子做AI缝纫自习室。',
     {'person': {'name': '吕杭', 'caption': '90后缝纫教父',
                 'chips': ['学缝纫', '做设计', '画图纸']}}),
    ('person', None, '乡村教师夫妻，用搭子运营公益组织的公众号。',
     {'person': {'name': '乡村教师夫妻', 'caption': '公益组织运营',
                 'chips': ['写文章', '做推广', '普及阅读']}}),
    ('cards3', None, '从个体创作者到一人公司，搭子在放大个体的能力边界。',
     {'cards': [{'title': '自媒体套件', 'sub': '选题到成片'}, {'title': '金融套件', 'sub': '研报级分析'},
                {'title': '教育套件', 'sub': '备课出题'}]}),
    ('media', 'crowd', '接下来，百度搭子还要把这套能力复制到千行百业。', {}),
    ('chips-dark', None, '百度搭子企业版：把公司沉淀的数据和经验，变成团队共享的AI能力。',
     {'title': '百度搭子 · 企业版', 'chips': ['知识库', 'skill', '智能体']}),
    ('chips-media', 'office', '比如新材料公司蓝海黑石，打通业务系统后，AI参与进了所有工作流程。',
     {'chips': ['企业管理', '采购分析', '会议协同']}),
    ('quote', None, '李彦宏曾提出AI时代的进化论。',
     {'quote': '智能体会自我进化，主动干活；人类个体要与AI共存，成为超级个体；企业要与智能体组队，成为超级组织。',
      'label': '李彦宏 · AI时代的进化论'}),
    ('number', 'crowd', '李彦宏预言：未来全球每天会有超过100亿的智能体参与人类工作。',
     {'number': '100亿', 'label': '李彦宏预言', 'caption': '智能体参与人类工作/天'}),
    ('media', 'chip', '今天的AI办公，只是这场变革的第一浪。', {}),
    ('chips-dark', None, '撑起搭子的，是背后百度的全栈能力。',
     {'title': '芯 · 云 · 模 · 体', 'chips': ['芯片', '云计算', '大模型', '智能体']}),
    ('media', 'chipfab', '竞争的重点是落地的速度：让AI参与所有工作流程，把技术变成新质生产力。', {}),
    ('checklist', None, '从这次实测就能看到：让AI写表格、做PPT，已经是小儿科的任务。',
     {'title': '任务进程', 'items': ['读取本地行业洞察报告', '整合网络搜索的市场数据', '分析行业趋势提炼洞察']}),
    ('media', 'tech', '现在的AI已经能完整接入生产流程，交付足够惊艳的成果。', {}),
    ('media', 'crowd', '未来每个人都会有自己的AI团队，每家公司都会成为超级组织。', {}),
    ('media', 'robot', '这场智能体革命，才刚刚开始。', {}),
    ('end', None, '', {'end': {'slogan': '有大事看 GetCut', 'highlight': 'GetCut'}}),
]

# ---------------- 1) 拷贝素材进渲染器 ----------------
media_dir = rr.RENDERER / 'public' / 'media'
media_dir.mkdir(parents=True, exist_ok=True)
media_map = {}
for key, rel in MEDIA_SRC.items():
    src = ROOT / rel
    uniq = 'rep__' + key + src.suffix
    dst = media_dir / uniq
    if not dst.exists() or dst.stat().st_size != src.stat().st_size:
        shutil.copyfile(src, dst)
    media_map[key] = uniq
print('素材就绪:', len(media_map))

# ---------------- 2) 组脚本 ----------------
script = ''.join(b[2] for b in BEATS)
print('脚本字数:', len(script))

# ---------------- 3) TTS ----------------
mp3, events = tts.synthesize(script, {}, WORK / 'tts', 'zh-CN-YunxiNeural', '+0%')
print('TTS 完成:', mp3.stat().st_size, 'bytes, events', len(events))

# ---------------- 4) 切句对齐 + 逐拍构建 ----------------
content = Content(schema_version=1, title='AI办公三国杀', script=script, sources=[], pronunciations={})
units = [t for (_, t) in split_clauses(content)]
timed_units = align_timeline([(i, u) for i, u in enumerate(units)], events)
assert len(timed_units) == len(units), '对齐后单元数不一致'

clean = lambda x: x.replace('，', '').replace('。', '').replace('、', '').replace('：', '').replace('？', '')
assign = [[] for _ in BEATS]
bi, taken = 0, 0
for u, tu in zip(units, timed_units):
    uc = clean(u)
    while bi < len(BEATS) - 1 and taken + len(uc) > len(clean(BEATS[bi][2])):
        bi += 1
        taken = 0
    assign[bi].append(tu)
    taken += len(uc)

shots, clauses_out = [], []
for bi, (mode, mk, text, params) in enumerate(BEATS):
    ts = assign[bi]
    if not ts:
        continue
    shot = {'kind': 'footage', 'startMs': round(ts[0].start_ms), 'endMs': round(ts[-1].end_ms),
            'stage': dict(mode=mode, **(params or {}))}
    if mk:
        uniq = media_map.get(mk)
        if uniq:
            shot['media'] = uniq
            shot['mediaKind'] = 'video'
    shots.append(shot)
    for tu in ts:
        clauses_out.append({'text': tu.text, 'startMs': round(tu.start_ms), 'endMs': round(tu.end_ms)})

total_ms = max(c['endMs'] for c in clauses_out) + 700
props = {
    'durationInFrames': int(total_ms / 1000 * 30) + 21,
    'template': 'zhigu',
    'showSubtitles': True,
    'headline': {'lines': [{'text': 'AI办公"三国杀"'}, {'text': '百度搭子 有多惊艳？'}]},
    'sources': [],
    'disclaimer': '',
    'clauses': clauses_out,
    'shots': shots,
}
print('拍数:', len(shots), '总时长:', round(total_ms / 1000, 1), 's')
(rr.RENDERER / 'props.json').write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding='utf-8')

# ---------------- 5) 渲染 + 混音 ----------------
visual = rr.render_visual(props, WORK / 'visual_out.mp4', timeout=3600)
print('视觉渲染完成:', visual)
audio = compose.mix_audio(mp3, total_ms / 1000.0, WORK, bgm=None)
final = compose.mux(WORK / 'visual_out.mp4', audio, ROOT / '_zhigu_replica.mp4', WORK)
print('DONE:', final)
