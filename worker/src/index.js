// Cloudflare Worker：浏览器端只调这里，key 不进前端。
//   POST /api/plan  {text}         → DeepSeek 拆稿
//   POST /api/tts   {text, voice}  → Azure 语音合成（mp3）
//   GET  /api/health               → 自检
//
// 需要配置的 secrets：
//   wrangler secret put DEEPSEEK_API_KEY
//   wrangler secret put AZURE_SPEECH_KEY
// 变量（wrangler.toml [vars]）：AZURE_REGION、AZURE_VOICE

const CORS = {
  'access-control-allow-origin': '*',
  'access-control-allow-headers': 'content-type',
  'access-control-allow-methods': 'POST, GET, OPTIONS',
};

const json = (body, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { ...CORS, 'content-type': 'application/json; charset=utf-8' },
  });

const SYSTEM = `你是短视频分镜导演。用户给你一段中文口播文案，你把它拆成一个个"画面任务"。

规则：
1. 按语义切分，一句一个镜头；每句 8~24 个字，太长拆两句，太短并到相邻句。
2. 第一个镜头必须是 hook，最后一个必须是 cta。
3. 每句选一个卡片类型：hook（开场钩子）/ stat（有明确数字）/ list（列举 2~4 件事）/ compare（做对比）/ quote（金句）/ plain（普通叙述）/ cta（行动指令）。
4. list 的 items 必须是 8~16 字的完整短语，不要只写名词。
5. 每句给 topic：4~10 字章节标签，同一段落用同一个。
6. 数字卡必须带量级：value 只写数字，"三万"写成 value:"3" unit:"万元"。
7. 只输出 JSON：{"beats":[{"text":"口播原句","card":"hook","topic":"章节","title":"","value":"","unit":"","label":"","items":[],"left":"","right":"","cta":""}]}`;

async function handlePlan(request, env) {
  const { text } = await request.json();
  const source = String(text || '').trim();
  if (source.length < 20) return json({ error: '文案太短了，至少 20 个字' }, 400);

  const res = await fetch('https://api.deepseek.com/chat/completions', {
    method: 'POST',
    headers: { 'content-type': 'application/json', authorization: `Bearer ${env.DEEPSEEK_API_KEY}` },
    body: JSON.stringify({
      model: 'deepseek-chat',
      temperature: 0.4,
      response_format: { type: 'json_object' },
      messages: [{ role: 'system', content: SYSTEM }, { role: 'user', content: source }],
    }),
  });
  if (!res.ok) return json({ error: `拆稿接口 ${res.status}` }, 502);
  const data = await res.json();
  let parsed;
  try { parsed = JSON.parse(data.choices?.[0]?.message?.content || '{}'); } catch { return json({ error: '模型返回的不是 JSON' }, 502); }

  const beats = (parsed.beats || []).filter((b) => b && String(b.text || '').trim());
  if (!beats.length) return json({ error: '拆不出分镜' }, 502);

  // 口播必须是用户原话：按原句顺序回填
  const sentences = source.split(/(?<=[。！？!?；;])/).map((s) => s.trim()).filter(Boolean)
    .map((s) => s.replace(/[。！？!?；;]$/, ''));
  if (sentences.length === beats.length) beats.forEach((b, i) => { b.text = sentences[i]; });
  else if (sentences.length > beats.length) {
    const head = sentences.slice(0, beats.length - 1);
    const tail = sentences.slice(beats.length - 1).join('，');
    beats.forEach((b, i) => { b.text = i === beats.length - 1 ? tail : head[i]; });
  } else {
    return json({ error: '镜头数和句子数对不上，请把文案按句号分段再试' }, 400);
  }
  return json({ beats });
}

async function handleTts(request, env) {
  const { text, voice } = await request.json();
  const src = String(text || '').trim();
  if (!src) return json({ error: '没有文本' }, 400);
  if (!env.AZURE_SPEECH_KEY) return json({ error: '服务端没配 AZURE_SPEECH_KEY，暂时没法配音' }, 501);

  const region = env.AZURE_REGION || 'eastasia';
  const voiceName = voice || env.AZURE_VOICE || 'zh-CN-YunxiNeural';
  const ssml = `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='zh-CN'>
    <voice name='${voiceName}'><prosody rate='+8%'>${escapeXml(src)}</prosody></voice></speak>`;

  const res = await fetch(`https://${region}.tts.speech.microsoft.com/cognitiveservices/v1`, {
    method: 'POST',
    headers: {
      'Ocp-Apim-Subscription-Key': env.AZURE_SPEECH_KEY,
      'Content-Type': 'application/ssml+xml',
      'X-Microsoft-OutputFormat': 'audio-24khz-48kbitrate-mono-mp3',
      'User-Agent': 'getcut',
    },
    body: ssml,
  });
  if (!res.ok) return json({ error: `语音服务 ${res.status}` }, 502);
  return new Response(res.body, {
    headers: { ...CORS, 'content-type': 'audio/mpeg', 'cache-control': 'no-store' },
  });
}

const escapeXml = (s) => s.replace(/[<>&'"]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;', "'": '&apos;', '"': '&quot;' }[c]));

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (request.method === 'OPTIONS') return new Response(null, { status: 204, headers: CORS });
    try {
      if (url.pathname === '/api/health') {
        return json({
          ok: Boolean(env.DEEPSEEK_API_KEY && env.AZURE_SPEECH_KEY),
          plan: Boolean(env.DEEPSEEK_API_KEY),
          tts: Boolean(env.AZURE_SPEECH_KEY),
        });
      }
      if (url.pathname === '/api/plan' && request.method === 'POST') return handlePlan(request, env);
      if (url.pathname === '/api/tts' && request.method === 'POST') return handleTts(request, env);
      return json({ error: 'not found' }, 404);
    } catch (e) {
      return json({ error: e instanceof Error ? e.message : String(e) }, 500);
    }
  },
};
