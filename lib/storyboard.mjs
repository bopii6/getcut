// 分镜：先把口播稿切成一句一句，再决定每句配哪个素材。
// 规则版（不联网）：句子按标点切，素材按顺序轮换，短句并到前一句，避免一秒一个镜头。
// 以后要接大模型，只换这一个文件，别的时间轴/渲染不动。

const SENT_END = /[。！？!?；;\n]+/;
const SOFT_END = /[，,、：:]/;

export function splitSentences(script) {
  const out = [];
  for (const chunk of String(script).split(SENT_END)) {
    const text = chunk.trim();
    if (!text) continue;
    const parts = text.split(SOFT_END).map((s) => s.trim()).filter(Boolean);
    if (parts.length <= 1) out.push(text);
    else out.push(...parts);
  }
  return out;
}

export function buildBeats(bundle, { minChars = 8 } = {}) {
  const sentences = splitSentences(bundle.script);
  if (!sentences.length) throw new Error('口播稿是空的，切不出分镜');

  const beats = [];
  for (const text of sentences) {
    const last = beats[beats.length - 1];
    if (last && last.text.length < minChars) last.text += `，${text}`;
    else beats.push({ text, assetIndex: -1 });
  }

  const usable = bundle.assets.filter((a) => a.kind === 'image' || a.kind === 'video');
  beats.forEach((b, i) => {
    b.asset = usable.length ? usable[i % usable.length] : null;
    b.assetIndex = usable.length ? i % usable.length : -1;
  });
  return beats;
}

/** 一行字幕最多几个字：1080 宽、56px 字号，14 个字大约顶到边。 */
export function wrapText(text, perLine = 14) {
  const lines = [];
  let line = '';
  for (const ch of text) {
    line += ch;
    if (line.length >= perLine) { lines.push(line); line = ''; }
  }
  if (line) lines.push(line);
  return lines.join('\n');
}
