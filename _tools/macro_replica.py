# -*- coding: utf-8 -*-
"""macro（宏观棱镜）1:1 复刻构建器：按《8月经济数据全部出炉》逐章建 props → TTS → 渲染 → 混音。

章节表抄自 _tools/_study/macro_breakdown.md（逐帧拆解）。
用法： cd videogen && python ../_tools/macro_replica.py
"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'videogen'))
from videogen.schemas import Content
from videogen import tts, compose, remotion_render as rr
from videogen.planner import align_timeline, split_clauses

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / '_replica_macro'
WORK.mkdir(exist_ok=True)

BG = 'rep__macro_bg.jpg'
CHANNEL = '@宏观棱镜'
SERIES = '8月经济数据解读'

# ---------------- 逐章分镜表 ----------------
# show: (kind, index) — 这句话念到时弹出第几个元素；None = 只说话
def L(i): return ('list', i)
def B(i): return ('bars', i)
def C(i): return ('cards', i)
BIG = ('big', 0)
CAP = ('caption', 0)

SECTIONS = [
    dict(kicker='总览', title='三种速度，一个经济', sub='8月经济数据 · 结构分化', rule=True,
         block={'type': 'list', 'items': ['出口跑得快', '消费迈不开', '投资继续退']},
         lines=[('8月经济数据今天新鲜出炉，', None), ('一句话总结：', None),
                ('出口跑得快，', L(0)), ('消费迈不开，', L(1)), ('投资继续退。', L(2))]),
    dict(kicker='总览', title='外需快，内需慢', sub='今年前8个月 · 同比变化', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '出口', 'value': 14.6, 'display': '+14.6%'},
             {'name': '社零', 'value': 1.1, 'display': '+1.1%'},
             {'name': '固定资产投资', 'value': -7.2, 'display': '-7.2%'}]},
         lines=[('今年前8个月，', None), ('出口增长14.6%，', B(0)),
                ('社会消费品零售总额只增长1.1%，', B(1)), ('固定资产投资下降7.2%，', B(2)),
                ('降幅持续扩大。', None)]),
    dict(kicker='体感分化', title='订单与现金流', sub='同一个经济，不同的经营处境', rule=True,
         block={'type': 'cards', 'rows': [
             {'text': '全球订单忙不过来'}, {'text': '房租、工资从哪来?'},
             {'text': '消费 → 投资 → 出口', 'gold': True}]},
         lines=[('同一个中国经济，', None), ('有的企业在接全球的订单忙不过来，', C(0)),
                ('有的老板却在考虑下个月的房租和工资从哪来。', C(1)),
                ('我们从消费、投资、出口三个方面，', C(2)), ('看看这种差异到底在哪里。', None)]),
    dict(kicker='01 / 消费', title='消费迈不开', sub='社会消费品零售总额同比增长速度', rule=False,
         block={'type': 'line', 'unit': '%', 'ticks': [10, 8, 6, 4, 2, 0, -2],
                'points': [{'x': '1-9月', 'y': 3.4}, {'x': '1-10月', 'y': 3.0}, {'x': '1-11月', 'y': 2.9},
                           {'x': '1-12月', 'y': 1.3}, {'x': '1-2月', 'y': 0.9}, {'x': '3月', 'y': 2.8},
                           {'x': '4月', 'y': 1.7}, {'x': '5月', 'y': 2.2}, {'x': '6月', 'y': 0.2},
                           {'x': '7月', 'y': 1.0}, {'x': '8月', 'y': -0.6}, {'x': '9月', 'y': 0.4}]},
         lines=[('先说与每个家庭最直接相关的消费。', None), ('前8个月，', None), ('社零增长1.1%；', None),
                ('单看8月，', None), ('只增长0.4%。', None)]),
    dict(kicker='01 / 消费', title='汽车拖累明显', sub='汽车类零售额 · 同比', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '前8个月', 'value': -13.9, 'display': '-13.9%'},
             {'name': '8月单月', 'value': -18.5, 'display': '-18.5%'}]},
         lines=[('汽车是其中一个明显的拖累。', None), ('前8个月汽车类零售额下降13.9%，', B(0)),
                ('8月单月下降18.5%。', B(1))]),
    dict(kicker='01 / 消费', title='去掉汽车，也不强', sub='前8个月 · 其他消费品零售额', rule=True,
         block={'type': 'big', 'number': '+2.7%', 'label': '同比增长'},
         lines=[('即使把汽车拿掉，', None), ('前8个月其他消费品零售额也只增长2.7%。', BIG),
                ('整个的消费依然没有从去年以旧换新的刺激透支中走出来。', CAP)],
         caption='以旧换新的刺激透支 · 消费仍未走出'),
    dict(kicker='01 / 消费', title='房价仍在承压', sub='1—8月 · 70个城市', rule=True,
         block={'type': 'big', 'number': '70 / 70', 'label': '二手房价格下跌', 'deco': 'dots'},
         lines=[('房地产相关的消费也在承压。', None), ('首先是1-8月70个城市的二手房价格全部下跌；', BIG),
                ('新房只有上海、杭州和合肥上涨。', CAP)],
         caption='上海 · 杭州 · 合肥：仅这三城新房上涨'),
    dict(kicker='01 / 消费', title='住房消费链承压', sub='前8个月 · 零售额同比', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '家具类', 'value': -4.9, 'display': '-4.9%'},
             {'name': '建筑及装潢材料', 'value': -9.8, 'display': '-9.8%'}]},
         lines=[('同时家具类零售额下降4.9%，', B(0)), ('建筑及装潢材料类下降9.8%。', B(1))]),
    dict(kicker='01 / 消费', title='仍有增长亮点', sub='前8个月 · 零售额同比', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '通讯器材', 'value': 16.3, 'display': '+16.3%'},
             {'name': '粮油食品', 'value': 6.8, 'display': '+6.8%'}]},
         lines=[('但也不是所有东西都卖不动。', None), ('同期通讯器材类零售额增长16.3%，', B(0)),
                ('粮油食品类增长6.8%。', B(1))]),
    dict(kicker='01 / 消费', title='家电出现企稳信号', sub='家电零售额 · 累计与单月', rule=True,
         block={'type': 'cards', 'rows': [
             {'text': '前8个月仍下降'}, {'text': '8月单月 +2.3%'}, {'text': '企稳信号', 'gold': True}]},
         lines=[('家电前8个月虽然仍在下降，', C(0)), ('但8月单月已经增长2.3%，', C(1)),
                ('算是一个企稳信号。', C(2))]),
    dict(kicker='02 / 投资', title='投资继续退', sub='固定资产投资（不含农户）同比增速', rule=True,
         block={'type': 'line', 'unit': '%', 'ticks': [5, 3, 1, -1, -3, -5, -7, -9],
                'points': [{'x': '1-9月', 'y': 0.5}, {'x': '1-10月', 'y': -0.5}, {'x': '1-11月', 'y': -1.7},
                           {'x': '1-12月', 'y': -2.6}, {'x': '1-2月', 'y': -3.8}, {'x': '3月', 'y': 1.8},
                           {'x': '4月', 'y': 1.7}, {'x': '5月', 'y': -1.6}, {'x': '6月', 'y': -4.1},
                           {'x': '7月', 'y': -5.7}, {'x': '8月', 'y': -6.7}, {'x': '9月', 'y': -7.2}]},
         lines=[('再看投资。', None), ('固定资产投资下降7.2%，', None), ('民间投资下降10.1%，', None),
                ('就连国资都投不动了，', None), ('下降了3.6%。', None)]),
    dict(kicker='02 / 投资', title='地产投资仍在下探', sub='全国房地产开发投资增速', rule=True,
         block={'type': 'line', 'unit': '%', 'ticks': [0, -5, -10, -15, -20, -25, -30],
                'points': [{'x': '1-9月', 'y': -12.9}, {'x': '1-10月', 'y': -13.9}, {'x': '1-11月', 'y': -14.7},
                           {'x': '1-12月', 'y': -15.9}, {'x': '1-2月', 'y': -17.2}, {'x': '3月', 'y': -11.1},
                           {'x': '4月', 'y': -11.2}, {'x': '5月', 'y': -13.7}, {'x': '6月', 'y': -16.2},
                           {'x': '7月', 'y': -18.0}, {'x': '8月', 'y': -19.2}, {'x': '9月', 'y': -19.9}]},
         lines=[('房地产开发投资下降19.9%，', None), ('降幅在继续扩大。', None)]),
    dict(kicker='02 / 投资', title='压力不只来自地产', sub='前8个月 · 投资同比', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '制造业', 'value': -2.3, 'display': '-2.3%'},
             {'name': '基础设施', 'value': -4.0, 'display': '-4%'}]},
         lines=[('同时制造业投资也下降2.3%，', B(0)), ('基础设施投资下降4%。', B(1)),
                ('这说明，投资的压力已经不能全部归到房地产头上。', CAP)],
         caption='投资压力已扩展至多个领域'),
    dict(kicker='03 / 出口', title='出口跑得快', sub='人民币计价 · 出口同比', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '前8个月', 'value': 14.6, 'display': '+14.6%'},
             {'name': '8月单月', 'value': 18.6, 'display': '+18.6%'}]},
         lines=[('最后看表现最强的出口。', None), ('前8个月，', None), ('人民币计价出口增长14.6%；', B(0)),
                ('8月单月增长18.6%。', B(1)), ('贸易顺差5.56万亿元。', CAP)],
         caption='贸易顺差 5.56万亿元'),
    dict(kicker='03 / 外贸', title='进出口两端增长', sub='前8个月 · 同比变化', rule=True,
         block={'type': 'big', 'number': '+22%', 'label': '进口增长'},
         lines=[('而且进口也不弱，', None), ('前8个月增长22%。', BIG),
                ('外贸是进出口两端都在增长。', CAP)],
         caption='进口 ↑ 出口 ↑：外贸两端都在增长'),
    dict(kicker='03 / 出口结构', title='工厂体感依然分化', sub='前8个月 · 分产品出口同比', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '机电产品', 'value': 21.9, 'display': '+21.9%'},
             {'name': '劳动密集型产品', 'value': -0.6, 'display': '-0.6%'}]},
         lines=[('但外贸好，不代表每一家工厂的生意都好。', None),
                ('出口的主要贡献依然是高附加产业，', CAP), ('机电产品增长21.9%，', B(0)),
                ('劳动密集型产品下降0.6%。', B(1))],
         caption='主要贡献来自高附加产业'),
    dict(kicker='03 / 汽车对照', title='同样是车，内外不同', sub='前8个月 · 内销与出口同比', rule=True,
         block={'type': 'bars', 'axis': True, 'rows': [
             {'name': '国内销售额', 'value': -13.9, 'display': '-13.9%'},
             {'name': '出口', 'value': 47.1, 'display': '+47.1%'}]},
         lines=[('有意思的是汽车在国内的销售额下滑13.9%，', B(0)), ('但是出口却增长了47.1%。', B(1))]),
    dict(kicker='结语', title='趋势没有明显变化', sub='出口快 · 消费慢 · 投资退', rule=False,
         block={'type': 'list', 'items': ['延续上半年的分化', '你的行业：订单多了吗?',
                                          '活没少干，钱更难赚?', '看懂宏观防走丢'],
                'gold_last': True},
         lines=[('总之到8月为止，一切跟上半年没有发生什么明显的趋势变化。', L(0)),
                ('也欢迎大家评论区聊聊：今年你所在的行业，', L(1)),
                ('还是活没少干，钱却更难赚了？', L(2)),
                ('欢迎关注收藏，看懂宏观防走丢。', L(3))]),
]

# ---------------- 1) 组脚本 ----------------
beats = []  # (section_idx, line_idx, text, show)
for si, sec in enumerate(SECTIONS):
    for li, (text, show) in enumerate(sec['lines']):
        beats.append((si, li, text, show))
script = ''.join(b[2] for b in beats)
print('脚本字数:', len(script), '句数:', len(beats))

# ---------------- 2) TTS ----------------
mp3, events = tts.synthesize(script, {}, WORK / 'tts', 'zh-CN-YunxiNeural', '+0%')
print('TTS 完成:', mp3.stat().st_size, 'bytes, events', len(events))

# ---------------- 3) 切句对齐 + 按字符贪心回填 ----------------
content = Content(schema_version=1, title=SERIES, script=script, sources=[], pronunciations={})
units = [t for (_, t) in split_clauses(content)]
timed = align_timeline([(i, u) for i, u in enumerate(units)], events)
assert len(timed) == len(units), '对齐后单元数不一致'

clean = lambda x: x.replace('，', '').replace('。', '').replace('、', '').replace('：', '').replace('；', '').replace('？', '').replace('？', '')
assigned = [[] for _ in beats]  # 每句台词 -> timed units
bi, taken = 0, 0
for u, tu in zip(units, timed):
    uc = clean(u)
    while bi < len(beats) - 1 and taken + len(uc) > len(clean(beats[bi][2])):
        bi += 1
        taken = 0
    assigned[bi].append(tu)
    taken += len(uc)

# ---------------- 4) 按章组装 shots ----------------
shots, clauses_out = [], []
for si, sec in enumerate(SECTIONS):
    sec_units = [tu for b, us in zip(beats, assigned) if b[0] == si for tu in us]
    if not sec_units:
        continue
    start_ms, end_ms = sec_units[0].start_ms, sec_units[-1].end_ms
    stage = {'mode': 'macro', 'kicker': sec['kicker'], 'title': sec['title'], 'sub': sec.get('sub'),
             'rule': sec.get('rule', False)}
    if sec.get('caption'):
        stage['caption'] = {'text': sec['caption'], 'atMs': 0}

    blk = sec['block']
    ats = {'list': [], 'bars': [], 'cards': []}
    big_at = None
    cap_at = None
    for (s_i, l_i, _text, show), us in zip(beats, assigned):
        if s_i != si or not us or show is None:
            continue
        kind, idx = show
        at = round(us[0].start_ms - start_ms)
        if kind in ('list', 'bars', 'cards'):
            ats[kind].append((idx, at))
        elif kind == 'big':
            big_at = at
        elif kind == 'caption':
            cap_at = at
    if blk['type'] == 'list':
        items = [{'text': t, 'atMs': a} for t, (i, a) in
                 sorted(zip(blk['items'], ats['list']), key=lambda x: x[1][1])]
        if blk.get('gold_last'):
            items[-1]['gold'] = True
        stage['block'] = {'type': 'list', 'rows': items}
    elif blk['type'] == 'bars':
        stage['block'] = {'type': 'bars', 'axis': blk.get('axis', True), 'rows': [
            dict(r, atMs=a) for r, (i, a) in sorted(zip(blk['rows'], ats['bars']), key=lambda x: x[1][1])]}
    elif blk['type'] == 'cards':
        stage['block'] = {'type': 'cards', 'rows': [
            dict(r, atMs=a) for r, (i, a) in sorted(zip(blk['rows'], ats['cards']), key=lambda x: x[1][1])]}
    elif blk['type'] == 'line':
        pts = [dict(p, label='%.1f' % p['y']) for p in blk['points']]
        stage['block'] = {'type': 'line', 'points': pts, 'ticks': blk['ticks'],
                          'unit': blk.get('unit'), 'spanMs': max(end_ms - start_ms - 300, 1200)}
    elif blk['type'] == 'big':
        stage['block'] = {'type': 'big', 'number': blk['number'], 'label': blk['label'],
                          'deco': blk.get('deco'), 'atMs': max(big_at or 0, 200)}
    if sec.get('caption'):
        stage['caption']['atMs'] = max(cap_at or 0, 200)

    shots.append({'kind': 'footage', 'startMs': round(start_ms), 'endMs': round(end_ms + 350),
                  'macroStage': stage})
    for tu in sec_units:
        clauses_out.append({'text': tu.text, 'startMs': round(tu.start_ms), 'endMs': round(tu.end_ms)})

total_ms = max(c['endMs'] for c in clauses_out) + 700
props = {
    'durationInFrames': int(total_ms / 1000 * 30) + 21,
    'template': 'macro',
    'showSubtitles': True,
    'watermark': False,
    'bgImage': BG,
    'channelName': CHANNEL,
    'headline': {'lines': [{'text': SERIES}]},
    'sources': [],
    'disclaimer': '',
    'clauses': clauses_out,
    'shots': shots,
}
print('章节数:', len(shots), '总时长:', round(total_ms / 1000, 1), 's')
(WORK / 'props.json').write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding='utf-8')
(rr.RENDERER / 'props.json').write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding='utf-8')

# ---------------- 5) 渲染 + 混音 ----------------
visual = rr.render_visual(props, WORK / 'visual_out.mp4', timeout=3600)
print('视觉渲染完成:', visual)
audio = compose.mix_audio(mp3, total_ms / 1000.0, WORK, bgm=None)
final = compose.mux(WORK / 'visual_out.mp4', audio, ROOT / '_macro_replica.mp4', WORK)
print('DONE:', final)
