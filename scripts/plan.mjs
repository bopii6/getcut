// 把一段文案拆成分镜：交给大模型判断"这句画什么"，失败就退回规则版。
// 输出是一份纯数据（见下方 schema），渲染层只认这份数据，不认文案。
import { readFile } from 'node:fs/promises';

export const CARD_TYPES = ['hook', 'plain', 'stat', 'list', 'compare', 'quote', 'cta'];

const SYSTEM = `你是短视频分镜导演。用户给你一段中文口播文案，你把它拆成一个个"画面任务"。

规则：
1. 按语义切分，一句一个镜头；每句 8~24 个字，太长就拆成两句，太短就并到相邻句。
2. 第一个镜头必须是 hook（3 秒内让人停下），最后一个镜头必须是 cta。
3. 每句选一个卡片类型：
   - hook：开场钩子，一句话砸在屏幕正中
   - stat：这句话里有明确数字/金额/比例/时长，就把数字单独放大
   - list：这句话在列举 2~4 件事（第一…第二…、三个坑、四个步骤）
   - compare：这句话在做对比（别人怎么…我们怎么…、以前…现在…）
   - quote：这是一句金句/观点，值得单独一屏
   - plain：普通叙述，只出字幕和背景
   - cta：结尾的行动指令（私信/评论/到店/加微信）
4. list 的 items 必须是 8~16 字的完整短语，带上判断或动作，不要只写名词：
   写"加盟费只是入场券"而不是"加盟费"；写"装修和押金最容易超预算"而不是"装修"。
5. 每句给 topic：4~10 字的章节标签，同一段落用同一个，像短视频顶部那行小标题
   （例如"三个数·投入""回本周期""谁在赚钱""结论"）。
6. 每句给 broll：2~4 个英文搜索词，描述这句该配什么实拍画面（例如 "restaurant owner meeting"、
   "contract signing closeup"、"city street night"）。要具体、好搜、不涉及品牌和人名。
7. 每句给 mediaHint：一句话描述想要的画面（"暖色办公桌特写"），没有具体素材时用空字符串。
8. 数字卡（stat）必须带量级：value 只写数字，"三万"写成 value:"3" unit:"万元"，不要写 unit:"元"。
9. 只输出 JSON，不要解释，不要 markdown 代码块。

输出 schema：
{"beats":[
  {"text":"口播原句（不要改写）","card":"hook","topic":"章节标签","title":"卡片上的大字（hook/quote 用）","value":"数字（stat 用）","unit":"单位","label":"数字的说明","items":["列点1","列点2"],"left":"对比左","right":"对比右","cta":"行动指令","broll":"english search words","mediaHint":""}
]}
没用的字段不要出现。`;

const CN_DIGIT = { 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };

function cnNumber(token) {
  // 只处理分镜里最常见的 1~999（三万、二十八、一百二）
  let total = 0;
  let section = 0;
  let digit = 0;
  for (const ch of token) {
    if (ch in CN_DIGIT) { digit = CN_DIGIT[ch]; continue; }
    if (ch === '十') { section += (digit || 1) * 10; digit = 0; continue; }
    if (ch === '百') { section += (digit || 1) * 100; digit = 0; continue; }
    if (ch === '千') { section += (digit || 1) * 1000; digit = 0; continue; }
  }
  total += section + digit;
  return total;
}

/**
 * 数字卡校正：大模型常把"三万"拆成 value=3、unit=元 —— 屏幕上就成了"3 元"。
 * 这里回原文找带量级的数字，拼回"3 万元"。
 */
export function normalizeStat(beat) {
  if (beat.card !== 'stat') return beat;
  const text = String(beat.text || '');
  // 先找带量级的大数（三万、28 万、1.2 亿），再退到"数字+单位"（47 天、4300 元）
  const big = text.match(/(\d+(?:\.\d+)?|[零一二两三四五六七八九十百千]+)\s*(万|亿)\s*(元|块)?/);
  let value;
  let unit;
  if (big) {
    const raw = big[1];
    value = /^\d/.test(raw) ? raw : String(cnNumber(raw));
    unit = `${big[2]}${big[3] || ''}`;
  } else {
    const small = text.match(/(\d+(?:\.\d+)?)\s*(元|块|人|位|天|年|个月|月|倍|家|件|分|%|次)/);
    if (!small) return beat;
    value = small[1];
    unit = small[2];
  }
  beat.value = value;
  beat.unit = unit;
  // 数字卡的说明必须来自同一句里数字附近，别用整句（会和张冠李戴的数字对不上）
  const around = text.slice(Math.max(0, text.indexOf(value) - 14), text.indexOf(value) + value.length + 14);
  if (!beat.label || !text.includes(beat.label)) beat.label = around.replace(/[，。！？；、]/g, ' ').trim();
  // 数字卡只留真数字（允许 71→96 这种区间）
  if (!/^[\d.]+(→[\d.]+)?$/.test(value)) {
    beat.card = 'quote';
    beat.title = beat.title || String(beat.text || '').trim();
    return beat;
  }
  // 屏幕上的数字必须真的出现在这句话里，否则就是大模型编的
  if (!text.includes(value) && !text.includes(Number(value).toString())) {
    beat.card = 'quote';
    beat.title = beat.title || String(beat.text || '').trim();
  }
  return beat;
}

export function rulePlan(text) {
  const clean = String(text).replace(/\s+/g, ' ').trim();
  const parts = clean
    .split(/(?<=[。！？!?；;])/)
    .map((s) => s.trim())
    .filter(Boolean);
  const beats = [];
  for (const p of parts) {
    const sentence = p.replace(/[。！？!?；;]$/, '');
    if (!sentence) continue;
    const num = sentence.match(/(\d+(?:\.\d+)?)\s*(万元|万|元|%|亿|人|天|年|个月|倍|家|件|分)/);
    if (num) {
      beats.push({ text: sentence, card: 'stat', value: num[1], unit: num[2], label: '' });
    } else if (/第一|第二|首先|其次|一是|二是|三个|四点/.test(sentence)) {
      beats.push({ text: sentence, card: 'list' });
    } else if (/但是|而|相比|别人|我们/.test(sentence) && sentence.length < 40) {
      beats.push({ text: sentence, card: 'compare' });
    } else {
      beats.push({ text: sentence, card: 'plain' });
    }
  }
  if (beats.length) beats[0].card = 'hook';
  if (beats.length > 1) beats[beats.length - 1].card = 'cta';
  return { beats: beats.map(normalizeStat) };
}

export async function planScript(text, { apiKey, model = 'deepseek-chat' } = {}) {
  const source = String(text || '').trim();
  if (!source) throw new Error('文案是空的');
  if (!apiKey) return rulePlan(source);

  const res = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${apiKey}` },
    body: JSON.stringify({
      model,
      temperature: 0.4,
      response_format: { type: 'json_object' },
      messages: [
        { role: 'system', content: SYSTEM },
        { role: 'user', content: source },
      ],
    }),
    signal: AbortSignal.timeout(120000),
  });
  if (!res.ok) throw new Error(`大模型接口 ${res.status}：${(await res.text()).slice(0, 200)}`);
  const data = await res.json();
  const raw = data.choices?.[0]?.message?.content || '';
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    throw new Error(`大模型没返回 JSON：${raw.slice(0, 200)}`);
  }
  const beats = (parsed.beats || []).filter((b) => b && String(b.text || '').trim());
  if (!beats.length) throw new Error('大模型拆不出分镜');
  for (const b of beats) {
    if (!CARD_TYPES.includes(b.card)) b.card = 'plain';
    b.text = String(b.text).trim();
  }
  // 模型很爱"顺手改稿"：口播必须用用户原话。按原句子顺序回填，只保留模型给的结构。
  const sentences = source
    .split(/(?<=[。！？!?；;])/).map((s) => s.trim()).filter(Boolean)
    .map((s) => s.replace(/[。！？!?；;]$/, ''));
  if (sentences.length === beats.length) {
    beats.forEach((b, i) => { b.text = sentences[i]; });
  } else if (sentences.length > beats.length) {
    // 句子比镜头多：多余的并到最后一个镜头
    const head = sentences.slice(0, beats.length - 1);
    const tail = sentences.slice(beats.length - 1).join('，');
    beats.forEach((b, i) => { b.text = i === beats.length - 1 ? tail : head[i]; });
  } else {
    // 镜头比句子多：模型自己补了句子，直接退回规则版，别让它改稿
    return rulePlan(source);
  }
  for (const b of beats) normalizeStat(b);
  return { beats };
}

export async function readScript(path) {
  return readFile(path, 'utf8');
}
