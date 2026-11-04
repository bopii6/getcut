// 素材包：一个 zip（或目录），里面是 content.json + manifest.json + images/ + videos/。
// 只认这一份协议，坏包当场说清楚哪一项不对——不要等到渲染到一半才崩。
import { readFile, stat } from 'node:fs/promises';
import path from 'node:path';

export async function loadBundle(dir) {
  const info = await stat(dir).catch(() => null);
  if (!info?.isDirectory()) throw new Error(`素材包目录不存在：${dir}`);

  const contentPath = path.join(dir, 'content.json');
  const raw = await readFile(contentPath, 'utf8').catch(() => {
    throw new Error('素材包里没有 content.json，这不是一个 GetCut 素材包');
  });

  let content;
  try {
    content = JSON.parse(raw);
  } catch (e) {
    throw new Error(`content.json 不是合法 JSON：${e.message}`);
  }
  if (!String(content.title || '').trim()) throw new Error('content.json 缺少 title（视频标题）');
  if (!String(content.script || '').trim()) throw new Error('content.json 缺少 script（口播稿）');

  let manifest = { assets: [] };
  try {
    manifest = JSON.parse(await readFile(path.join(dir, 'manifest.json'), 'utf8'));
  } catch {
    // manifest 可选：没有素材清单就退化成纯文字卡
  }
  const assets = Array.isArray(manifest.assets) ? manifest.assets : [];
  for (const a of assets) {
    if (!a?.file) continue;
    const abs = path.join(dir, a.file);
    const ok = await stat(abs).then((s) => s.isFile()).catch(() => false);
    if (!ok) throw new Error(`manifest 里列了 ${a.file}，但压缩包里没有这个文件`);
  }

  return {
    dir,
    title: String(content.title).trim(),
    script: String(content.script).trim(),
    hookTitle: content.hook_headline?.text ? String(content.hook_headline.text) : null,
    hookTag: content.hook_headline?.tag ? String(content.hook_headline.tag) : null,
    sources: Array.isArray(content.sources) ? content.sources.filter(Boolean) : [],
    assets: assets.map((a) => ({
      file: a.file,
      absPath: path.join(dir, a.file),
      kind: a.kind === 'video' ? 'video' : 'image',
      summary: a.summary || '',
    })),
  };
}
