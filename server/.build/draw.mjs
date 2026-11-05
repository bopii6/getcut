// app/src/lib/theme.ts
var PALETTES = {
  poster: {
    bg1: "#080807",
    bg2: "#17130d",
    glow: "rgba(255,212,0,0.20)",
    ink: "#f7f2e6",
    muted: "rgba(247,242,230,0.55)",
    accent: "#ffd400",
    accentInk: "#0a0906",
    hairline: "rgba(247,242,230,0.16)",
    panel: "rgba(247,242,230,0.06)",
    panelEdge: "rgba(255,212,0,0.45)",
    dark: true
  },
  magazine: {
    bg1: "#f6f2e9",
    bg2: "#e9e1d2",
    glow: "rgba(192,57,43,0.16)",
    ink: "#14100c",
    muted: "rgba(20,16,12,0.55)",
    accent: "#c0392b",
    accentInk: "#fff8f2",
    hairline: "rgba(20,16,12,0.16)",
    panel: "rgba(255,255,255,0.6)",
    panelEdge: "rgba(192,57,43,0.4)",
    dark: false
  },
  dashboard: {
    bg1: "#06101f",
    bg2: "#0b1b2e",
    glow: "rgba(64,169,255,0.22)",
    ink: "#e9f2ff",
    muted: "rgba(233,242,255,0.55)",
    accent: "#40a9ff",
    accentInk: "#04121f",
    hairline: "rgba(233,242,255,0.16)",
    panel: "rgba(233,242,255,0.06)",
    panelEdge: "rgba(64,169,255,0.5)",
    dark: true
  },
  news: {
    bg1: "#f7f5f2",
    bg2: "#e6e2dc",
    glow: "rgba(214,40,40,0.14)",
    ink: "#141414",
    muted: "rgba(20,20,20,0.55)",
    accent: "#d62828",
    accentInk: "#fff7f4",
    hairline: "rgba(20,20,20,0.18)",
    panel: "rgba(255,255,255,0.7)",
    panelEdge: "rgba(214,40,40,0.45)",
    dark: false
  },
  broadsheet: {
    bg1: "#F3EDE1",
    bg2: "#F3EDE1",
    glow: "rgba(165,18,26,0.08)",
    ink: "#141414",
    muted: "rgba(20,20,20,0.55)",
    accent: "#A5121A",
    accentInk: "#FFFFFF",
    hairline: "rgba(20,20,20,0.2)",
    panel: "rgba(0,0,0,0.03)",
    panelEdge: "#141414",
    dark: false
  },
  cover: {
    bg1: "#EDE6DA",
    bg2: "#EDE6DA",
    glow: "rgba(43,60,255,0.14)",
    ink: "#141414",
    muted: "rgba(20,20,20,0.55)",
    accent: "#2B3CFF",
    accentInk: "#FFFFFF",
    hairline: "rgba(20,20,20,0.2)",
    panel: "#FFFFFF",
    panelEdge: "#141414",
    dark: false
  },
  reel: {
    bg1: "#0B0A09",
    bg2: "#0B0A09",
    glow: "rgba(217,130,43,0.2)",
    ink: "#F0E6D6",
    muted: "rgba(240,230,214,0.5)",
    accent: "#D9822B",
    accentInk: "#0B0A09",
    hairline: "rgba(240,230,214,0.16)",
    panel: "#2A1F18",
    panelEdge: "#6B4A32",
    dark: true
  },
  marker: {
    bg1: "#F7F4EC",
    bg2: "#F7F4EC",
    glow: "rgba(229,52,43,0.10)",
    ink: "#141414",
    muted: "rgba(20,20,20,0.55)",
    accent: "#E5342B",
    accentInk: "#FFFFFF",
    hairline: "rgba(20,20,20,0.18)",
    panel: "#FFFFFF",
    panelEdge: "#141414",
    dark: false
  },
  swiss: {
    bg1: "#F7F7F5",
    bg2: "#F7F7F5",
    glow: "rgba(226,35,26,0.08)",
    ink: "#111111",
    muted: "rgba(17,17,17,0.55)",
    accent: "#E2231A",
    accentInk: "#FFFFFF",
    hairline: "rgba(17,17,17,0.16)",
    panel: "rgba(0,0,0,0.03)",
    panelEdge: "rgba(17,17,17,0.3)",
    dark: false
  },
  terminal: {
    bg1: "#050607",
    bg2: "#050607",
    glow: "rgba(57,255,136,0.14)",
    ink: "#E8FFF2",
    muted: "rgba(232,255,242,0.5)",
    accent: "#39FF88",
    accentInk: "#050607",
    hairline: "#16201A",
    panel: "#0A0F0C",
    panelEdge: "#1E2A22",
    dark: true
  },
  newsroom: {
    bg1: "#0C1B2A",
    bg2: "#0C1B2A",
    glow: "rgba(216,35,42,0.16)",
    ink: "#FFFFFF",
    muted: "rgba(255,255,255,0.55)",
    accent: "#D8232A",
    accentInk: "#FFFFFF",
    hairline: "rgba(255,255,255,0.16)",
    panel: "rgba(16,35,58,0.92)",
    panelEdge: "rgba(44,90,142,0.8)",
    dark: true
  },
  ledger: {
    bg1: "#08090A",
    bg2: "#08090A",
    glow: "rgba(200,255,0,0.12)",
    ink: "#F2F3F5",
    muted: "rgba(242,243,245,0.55)",
    accent: "#C8FF00",
    accentInk: "#08090A",
    hairline: "#23262B",
    panel: "rgba(255,255,255,0.04)",
    panelEdge: "#2E3238",
    dark: true
  },
  night: {
    bg1: "#0b0a16",
    bg2: "#161232",
    glow: "rgba(124,108,255,0.25)",
    ink: "#ece9ff",
    muted: "rgba(236,233,255,0.55)",
    accent: "#a78bfa",
    accentInk: "#120c26",
    hairline: "rgba(236,233,255,0.16)",
    panel: "rgba(236,233,255,0.06)",
    panelEdge: "rgba(167,139,250,0.5)",
    dark: true
  }
};

// app/src/lib/styles.ts
var W = 1080;
var H = 1920;
var HEAVY = '"Microsoft YaHei","PingFang SC",sans-serif';
var LIGHT = '"Microsoft YaHei Light","PingFang SC","Microsoft YaHei",sans-serif';
var ease = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
function wrap(ctx, text, maxWidth) {
  const out = [];
  let line = "";
  for (const ch of text) {
    const next = line + ch;
    if (ctx.measureText(next).width > maxWidth && line) {
      out.push(line);
      line = ch;
    } else line = next;
  }
  if (line) out.push(line);
  return out;
}
var NEWS = {
  bg: "#0C1B2A",
  ink: "#FFFFFF",
  red: "#D8232A",
  blue: "#1E4E8C",
  dim: "#7C93AD"
};
function newsTop(ctx, beat, t, index, total) {
  const wipe = ease(t / 0.3);
  ctx.fillStyle = NEWS.bg;
  ctx.fillRect(0, 0, W, 96);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(24, 20, 96 * wipe, 56);
  ctx.fillStyle = "#fff";
  ctx.font = `900 34px ${HEAVY}`;
  ctx.fillText("LIVE", 42, 60);
  ctx.font = `900 40px ${HEAVY}`;
  const topic = beat.topic || "\u73B0\u573A\u62A5\u9053";
  ctx.fillText(topic, 140, 62);
  ctx.font = `400 26px ${LIGHT}`;
  ctx.fillStyle = NEWS.dim;
  const tc = `${String(20 + index % 4).padStart(2, "0")}:14:${String(index * 7 % 60).padStart(2, "0")}`;
  ctx.fillText(tc, 900, 60);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 96, W, 54 * wipe);
  ctx.fillStyle = "#fff";
  ctx.font = `400 24px ${LIGHT}`;
  ctx.fillText("S P E C I A L   R E P O R T   \uFF0F   \u7279 \u522B \u62A5 \u9053", 64, 133);
  ctx.font = `900 84px ${HEAVY}`;
  const lines = wrap(ctx, beat.title || beat.text, 840).slice(0, 2);
  ctx.fillStyle = NEWS.ink;
  lines.forEach((ln, i) => {
    const s = ease((t - 0.12 - i * 0.06) / 0.25);
    if (s <= 0) return;
    ctx.save();
    ctx.globalAlpha = s;
    ctx.translate(0, (1 - s) * 18);
    ctx.fillText(ln, 64, 236 + i * 84);
    ctx.restore();
  });
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(40, 150, 6, 170);
  ctx.strokeStyle = "rgba(255,255,255,.5)";
  ctx.lineWidth = 1;
  ctx.strokeRect(930, 150, 72, 72);
  ctx.font = `400 20px ${LIGHT}`;
  ctx.fillStyle = "#fff";
  ctx.fillText("HD", 950, 194);
  ctx.fillStyle = "rgba(255,255,255,.14)";
  ctx.fillRect(0, 290, W, 3);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 290, W * (index + 1) / total, 3);
}
function newsStage(ctx, beat, t) {
  ctx.strokeStyle = "rgba(27,51,80,.55)";
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 48) {
    ctx.beginPath();
    ctx.moveTo(x, 300);
    ctx.lineTo(x, 1300);
    ctx.stroke();
  }
  for (let y = 300; y < 1300; y += 48) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(W, y);
    ctx.stroke();
  }
  ctx.strokeStyle = "rgba(30,78,140,.3)";
  [380, 480, 580].forEach((r) => {
    ctx.beginPath();
    ctx.arc(540, 1300, r, Math.PI, 0);
    ctx.stroke();
  });
  ctx.fillStyle = "rgba(16,35,58,.92)";
  ctx.fillRect(90, 430, 900, 540);
  ctx.strokeStyle = "#2C5A8E";
  ctx.lineWidth = 1;
  ctx.strokeRect(90, 430, 900, 540);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(90, 430, 4, 64);
  const items = (beat.items?.length ? beat.items : String(beat.text).split(/[，。；]/)).filter(Boolean).slice(0, 3);
  const numRaw = String(beat.value || "").replace(/[^\d.]/g, "");
  if (numRaw && (beat.card === "stat" || beat.card === "compare" || beat.card === "plain")) {
    const p = Math.min(1, t / 0.5);
    const shown = String(Math.round(Number(numRaw) * p));
    ctx.fillStyle = NEWS.red;
    ctx.fillRect(140, 520, 120 * ease(t / 0.3), 6);
    ctx.font = "900 300px " + HEAVY;
    ctx.fillStyle = "#fff";
    ctx.fillText(shown, 120, 860);
    const nw = ctx.measureText(shown).width;
    ctx.font = "900 72px " + HEAVY;
    ctx.fillStyle = NEWS.red;
    ctx.fillText(beat.unit || "", 120 + nw + 24, 850);
    ctx.font = "900 44px " + HEAVY;
    ctx.fillStyle = "rgba(255,255,255,.85)";
    ctx.fillText((beat.label || beat.title || "").slice(0, 14), 120, 960);
    return;
  }
  if (beat.card === "hook" || beat.card === "quote" || items.length === 0) {
    ctx.font = "900 92px " + HEAVY;
    ctx.fillStyle = "#fff";
    const big = wrap(ctx, beat.title || beat.text, 900).slice(0, 4);
    big.forEach((ln, i) => {
      const s2 = ease((t - 0.15 - i * 0.08) / 0.3);
      ctx.save();
      ctx.globalAlpha = s2;
      ctx.fillText(ln, 90, 560 + i * 118);
      ctx.restore();
    });
    return;
  }
  items.forEach((item, i) => {
    const s = ease((t - 0.2 - i * 0.12) / 0.3);
    if (s <= 0) return;
    const y = 505 + i * 150;
    ctx.save();
    ctx.globalAlpha = s;
    ctx.fillStyle = NEWS.red;
    ctx.fillRect(140, y - 36, 40, 40);
    ctx.fillStyle = "#fff";
    ctx.font = `900 26px ${HEAVY}`;
    ctx.fillText(String(i + 1).padStart(2, "0"), 150, y - 7);
    ctx.font = `900 52px ${HEAVY}`;
    ctx.fillStyle = "#fff";
    let line = item;
    const maxW = 720;
    if (ctx.measureText(line).width > maxW) {
      while (line.length > 2 && ctx.measureText(line + "\u2026").width > maxW) line = line.slice(0, -1);
      line += "\u2026";
    }
    ctx.fillText(line, 210, y);
    ctx.fillStyle = "rgba(30,62,96,.9)";
    ctx.fillRect(140, y + 42, 760, 1);
    ctx.fillStyle = "#9DB4CC";
    ctx.font = `900 26px ${HEAVY}`;
    ctx.fillText("\u203A", 920, y + 8);
    ctx.restore();
  });
}
function newsBottom(ctx, beat, t) {
  ctx.fillStyle = "rgba(12,27,42,.96)";
  ctx.fillRect(0, 1420, W, 140);
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 1420, 24, 140);
  ctx.font = `900 58px ${HEAVY}`;
  ctx.fillStyle = "#fff";
  const lines = wrap(ctx, String(beat.text), 860).slice(0, 2);
  lines.forEach((ln, i) => ctx.fillText(ln, 96, 1478 + i * 62));
  ctx.fillStyle = NEWS.red;
  ctx.fillRect(0, 1560, W, 56);
  ctx.save();
  ctx.beginPath();
  ctx.rect(0, 1560, W, 56);
  ctx.clip();
  ctx.font = `400 28px ${LIGHT}`;
  ctx.fillStyle = "#fff";
  const text = "  \u25CF \u5F00\u5E97\u4E09\u4E2A\u6570\uFF1A\u6295\u5165 \xB7 \u56DE\u672C \xB7 \u6D41\u6C34    \u25CF \u8BC4\u8BBA\u533A\u6253\u300C\u9884\u7B97\u300D\u9886\u6E05\u5355    \u25CF \u672C\u7247\u7531 GetCut \u751F\u6210  ";
  const w = ctx.measureText(text).width;
  const off = t * 60 % w;
  ctx.fillText(text, 24 - off, 1598);
  ctx.fillText(text, 24 - off + w, 1598);
  ctx.restore();
}
function drawNewsroom(ctx, beat, t, index, total, layout = "auto") {
  if (layout === "big") beat = { ...beat, card: "hook" };
  if (layout === "data") beat = { ...beat, card: "stat", value: beat.value || "132" };
  if (layout === "content" && (beat.card === "hook" || beat.card === "quote")) beat = { ...beat, card: "plain" };
  ctx.fillStyle = NEWS.bg;
  ctx.fillRect(0, 0, W, H);
  newsTop(ctx, beat, t, index, total);
  newsStage(ctx, beat, t);
  newsBottom(ctx, beat, t);
}
var MK = { bg: "#F7F4EC", ink: "#141414", red: "#E5342B", yellow: "#FFD400", sub: "#6B6B6B" };
function wobbleRect(ctx, x, y, w, h, rnd) {
  ctx.beginPath();
  const j = (n) => Math.sin(rnd + n * 12.9898) * 2.6;
  ctx.moveTo(x + j(1), y + j(2));
  ctx.lineTo(x + w + j(3), y + j(4));
  ctx.lineTo(x + w + j(5), y + h + j(6));
  ctx.lineTo(x + j(7), y + h + j(8));
  ctx.closePath();
}
function drawMarker(ctx, beat, t, index, _total, layout = "auto") {
  if (layout === "big") beat = { ...beat, card: "hook" };
  if (layout === "content" && (beat.card === "hook" || beat.card === "quote")) beat = { ...beat, card: "list" };
  ctx.fillStyle = MK.bg;
  ctx.fillRect(0, 0, W, H);
  ctx.save();
  ctx.globalAlpha = 0.06;
  ctx.fillStyle = "#fff";
  for (let i = 0; i < 3; i++) {
    ctx.save();
    ctx.translate(120 + i * 300, 300 + i * 380);
    ctx.rotate((-20 + i * 3) * Math.PI / 180);
    ctx.fillRect(0, 0, 120, 900);
    ctx.restore();
  }
  ctx.restore();
  if (beat.card === "hook" || beat.card === "quote") {
    const big = wrap(ctx, beat.title || beat.text, 860).slice(0, 4);
    ctx.font = "900 104px " + HEAVY;
    ctx.fillStyle = MK.ink;
    big.forEach((ln, i) => {
      const p = ease((t - 0.12 - i * 0.1) / 0.3);
      ctx.save();
      ctx.globalAlpha = p;
      ctx.fillText(ln, 78, 620 + i * 132);
      ctx.restore();
    });
    const uw = 700 * ease((t - 0.4) / 0.4);
    ctx.strokeStyle = MK.yellow;
    ctx.lineWidth = 16;
    ctx.beginPath();
    for (let x = 0; x < uw; x += 9) {
      const y = 690 + Math.sin(x / 30) * 7;
      if (x === 0) ctx.moveTo(80 + x, y);
      else ctx.lineTo(80 + x, y);
    }
    ctx.stroke();
    ctx.strokeStyle = MK.red;
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.ellipse(940, 180, 56, 52, 0.1, 0, Math.PI * 2);
    ctx.stroke();
    ctx.font = "900 54px " + HEAVY;
    ctx.fillStyle = MK.red;
    ctx.fillText(String(index + 1).padStart(2, "0"), 910, 200);
    return;
  }
  const title = beat.title || beat.topic || beat.text;
  ctx.font = "900 66px " + HEAVY;
  const lines = wrap(ctx, title, 820).slice(0, 2);
  ctx.strokeStyle = MK.ink;
  ctx.lineWidth = 4;
  const boxH = lines.length * 80 + 26;
  const boxW = Math.min(880, Math.max(...lines.map((l) => ctx.measureText(l).width)) + 56);
  wobbleRect(ctx, 64, 92, boxW, boxH, 3);
  ctx.stroke();
  ctx.fillStyle = MK.ink;
  lines.forEach((ln, i) => ctx.fillText(ln, 88, 160 + i * 80));
  const bw = 620 * ease(t / 0.4);
  ctx.strokeStyle = MK.yellow;
  ctx.lineWidth = 12;
  ctx.beginPath();
  for (let x = 0; x < bw; x += 8) {
    const y = 120 + boxH + Math.sin(x / 26) * 6;
    if (x === 0) ctx.moveTo(80 + x, y);
    else ctx.lineTo(80 + x, y);
  }
  ctx.stroke();
  ctx.strokeStyle = MK.red;
  ctx.lineWidth = 5;
  ctx.beginPath();
  ctx.ellipse(940, 130, 54, 50, 0.1, 0, Math.PI * 2);
  ctx.stroke();
  ctx.font = "900 52px " + HEAVY;
  ctx.fillStyle = MK.red;
  ctx.fillText(String(index + 1).padStart(2, "0"), 912, 150);
  const items = (beat.items?.length ? beat.items : String(beat.text).split(/[，。；]/)).filter(Boolean).slice(0, 3);
  const startY = 640;
  items.forEach((item, i) => {
    const p = ease((t - 0.15 - i * 0.1) / 0.35);
    if (p <= 0) return;
    const y = startY + i * 210;
    ctx.save();
    ctx.globalAlpha = p;
    ctx.translate((1 - p) * -20, 0);
    ctx.fillStyle = "rgba(0,0,0,0.12)";
    ctx.fillRect(84, y + 10, 880, 170);
    ctx.fillStyle = "#FFFFFF";
    ctx.fillRect(76, y, 880, 170);
    ctx.strokeStyle = MK.ink;
    ctx.lineWidth = 2;
    ctx.strokeRect(76, y, 880, 170);
    ctx.fillStyle = MK.ink;
    ctx.font = "900 40px " + HEAVY;
    ctx.fillText(String(i + 1), 108, y + 108);
    ctx.font = "900 52px " + HEAVY;
    const txt = wrap(ctx, item, 720)[0];
    ctx.fillText(txt, 168, y + 104);
    ctx.restore();
  });
  ctx.font = "900 54px " + HEAVY;
  const sub = wrap(ctx, String(beat.text), 860).slice(0, 2);
  const subY = 1470;
  ctx.fillStyle = "rgba(255,212,0,0.55)";
  const subW = Math.max(...sub.map((l) => ctx.measureText(l).width));
  ctx.fillRect((W - subW) / 2 - 10, subY + 20, (subW + 20) * ease(t / 0.5), 24);
  ctx.fillStyle = "#111";
  sub.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, subY + i * 62);
  });
  ctx.font = "400 22px " + LIGHT;
  ctx.fillStyle = "#8A857C";
  ctx.fillText("\u677F\u4E66 \xB7 \u7B2C " + (index + 1) + " \u9875", 64, H - 90);
  ctx.fillText("GETCUT", W - 64 - ctx.measureText("GETCUT").width, H - 90);
}
var SW = { bg: "#F7F7F5", ink: "#111111", red: "#E2231A", gray: "#8A8A8A" };
function drawSwiss(ctx, beat, t, index, total, layout = "auto") {
  ctx.fillStyle = SW.bg;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = SW.red;
  ctx.beginPath();
  ctx.arc(78, 96, 12, 0, Math.PI * 2);
  ctx.fill();
  ctx.font = "400 24px " + LIGHT;
  ctx.fillStyle = SW.gray;
  ctx.fillText(`${String(index + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`, 104, 104);
  const right = "STRATEGY";
  ctx.fillText(right, 1008 - ctx.measureText(right).width, 104);
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 120, 936 * ease(t / 0.3), 1);
  if (layout === "big" || layout === "auto" && (beat.card === "hook" || beat.card === "quote")) {
    ctx.font = "900 120px " + HEAVY;
    ctx.fillStyle = SW.ink;
    const big = wrap(ctx, beat.title || beat.text, 900).slice(0, 4);
    big.forEach((ln, i) => {
      const p2 = ease((t - 0.15 - i * 0.1) / 0.3);
      ctx.save();
      ctx.globalAlpha = p2;
      ctx.fillText(ln, 72, 480 + i * 140);
      ctx.restore();
    });
    ctx.fillStyle = SW.red;
    const sq2 = 64 * ease((t - 0.3) / 0.25);
    ctx.fillRect(72, 380, sq2, sq2);
    return;
  }
  ctx.font = "900 92px " + HEAVY;
  ctx.fillStyle = SW.ink;
  const lines = wrap(ctx, beat.title || beat.topic || beat.text, 880).slice(0, 2);
  lines.forEach((ln, i) => ctx.fillText(ln, 72, 220 + i * 100));
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 380, 388 * ease(t / 0.4), 2);
  const raw = String(beat.value || "").replace(/[^\d.]/g, "");
  const num = Number(raw);
  const p = Math.min(1, t / 0.5);
  const shown = Number.isFinite(num) && raw ? String(Math.round(num * p)) : beat.value || "";
  ctx.font = "900 360px " + HEAVY;
  ctx.fillStyle = SW.ink;
  ctx.fillText(shown, 60, 800);
  const wNum = ctx.measureText(shown).width;
  ctx.font = "900 72px " + HEAVY;
  ctx.fillText(beat.unit || "", 72 + wNum + 28, 790);
  ctx.fillStyle = SW.red;
  const sq = 90 * ease((t - 0.2) / 0.25);
  ctx.fillRect(820, 470, sq, sq);
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 840, 936, 1);
  ctx.font = "400 34px " + LIGHT;
  ctx.fillStyle = "#333";
  const body = wrap(ctx, beat.label || String(beat.text), 860).slice(0, 2);
  body.forEach((ln, i) => ctx.fillText(ln, 72, 920 + i * 50));
  ctx.fillStyle = SW.ink;
  ctx.fillRect(72, 1400, 936, 1);
  ctx.font = "900 54px " + HEAVY;
  const sub = wrap(ctx, String(beat.text), 860).slice(0, 2);
  sub.forEach((ln, i) => ctx.fillText(ln, 72, 1470 + i * 62));
  ctx.font = "400 18px " + LIGHT;
  ctx.fillStyle = "#999";
  ctx.fillText("1080\xD71920 \uFF0F 30FPS \uFF0F GETCUT", 72, 1640);
  ctx.fillStyle = "#BBB";
  ctx.fillText(String(index + 1).padStart(2, "0"), 970, 1300);
}
var BS = { paper: "#F3EDE1", ink: "#141414", red: "#A5121A", gray: "#6E6659" };
function halftone(ctx, cx, cy, r, cell = 12) {
  ctx.fillStyle = BS.ink;
  for (let y = -r; y <= r; y += cell) {
    for (let x = -r; x <= r; x += cell) {
      const d = Math.sqrt(x * x + y * y) / r;
      if (d > 1) continue;
      const dot = 0.6 + (1 - d) * 3.6;
      ctx.beginPath();
      ctx.arc(cx + x, cy + y, dot, 0, Math.PI * 2);
      ctx.fill();
    }
  }
}
function drawBroadsheet(ctx, beat, t, index, _total, layout = "auto") {
  if (layout === "big") beat = { ...beat, card: "hook" };
  if (layout === "content" && (beat.card === "hook" || beat.card === "quote")) beat = { ...beat, card: "plain" };
  ctx.fillStyle = BS.paper;
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 40, 952, 3);
  ctx.font = "900 92px " + HEAVY;
  const mast = "\u6BCF \u65E5 \u5546 \u8BAF";
  ctx.fillText(mast, (W - ctx.measureText(mast).width) / 2, 130);
  ctx.font = "400 20px " + LIGHT;
  ctx.fillStyle = BS.gray;
  ctx.fillText("\u521B\u520A\u4E8E 2019", 64, 128);
  const issue = "\u7B2C " + (100 + index) + " \u671F";
  ctx.fillText(issue, 1016 - ctx.measureText(issue).width, 128);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 136, 952, 1);
  ctx.font = "400 22px " + LIGHT;
  ctx.fillStyle = BS.gray;
  ctx.fillText("2026 \u5E74 11 \u6708 4 \u65E5 \u661F\u671F\u4E09", 64, 176);
  const price = "\u96F6\u552E\u4EF7 \xA51.00";
  ctx.fillText(price, 1016 - ctx.measureText(price).width, 176);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 190, 952, 1);
  ctx.font = "900 80px " + HEAVY;
  ctx.fillStyle = BS.ink;
  const title = wrap(ctx, beat.title || beat.topic || beat.text, 860).slice(0, 2);
  title.forEach((ln, i) => ctx.fillText(ln, 64, 330 + i * 90));
  ctx.fillStyle = BS.red;
  ctx.fillRect(64, 206, 96, 36);
  ctx.fillStyle = "#fff";
  ctx.font = "900 24px " + HEAVY;
  ctx.fillText("\u72EC\u5BB6", 82, 232);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 440, 952, 2);
  if (beat.card === "hook" || beat.card === "quote") {
    ctx.font = "900 116px " + HEAVY;
    ctx.fillStyle = BS.ink;
    const big = wrap(ctx, beat.title || beat.text, 920).slice(0, 4);
    big.forEach((ln, i) => {
      const p = ease((t - 0.12 - i * 0.08) / 0.3);
      ctx.save();
      ctx.globalAlpha = p;
      ctx.fillText(ln, 64, 600 + i * 140);
      ctx.restore();
    });
    ctx.fillStyle = BS.red;
    ctx.fillRect(64, 560, 160 * ease(t / 0.35), 8);
    ctx.font = "400 28px " + LIGHT;
    ctx.fillStyle = BS.gray;
    ctx.fillText("\u2014\u2014 \u672C\u62A5\u8BB0\u8005", 64, 1240);
    return;
  }
  ctx.fillRect(506, 460, 1, 500);
  ctx.font = "400 26px " + LIGHT;
  ctx.fillStyle = "#2B2720";
  const body = wrap(ctx, `${beat.label || ""}${String(beat.text)}`, 400).slice(0, 5);
  body.forEach((ln, i) => ctx.fillText(ln, 64, 510 + i * 48));
  halftone(ctx, 760, 600, 150);
  ctx.font = "400 20px " + LIGHT;
  ctx.fillStyle = BS.gray;
  ctx.fillText("\u56FE\uFF1A2019\u20142026 \u95E8\u5E97\u589E\u957F", 560, 780);
  ctx.strokeStyle = BS.ink;
  ctx.lineWidth = 3;
  ctx.strokeRect(64, 830, 952, 180);
  ctx.lineWidth = 1;
  ctx.strokeRect(74, 840, 932, 160);
  ctx.font = "900 56px " + HEAVY;
  ctx.fillStyle = BS.ink;
  const quote = beat.value ? `${beat.value}${beat.unit || ""}` : title[0] || "";
  const qw = ctx.measureText(quote).width;
  ctx.fillText(quote, (W - qw) / 2, 920);
  ctx.font = "400 24px " + LIGHT;
  ctx.fillStyle = BS.gray;
  const by = "\u2014\u2014 \u672C\u62A5\u8BB0\u8005";
  ctx.fillText(by, (W - ctx.measureText(by).width) / 2, 970);
  ctx.fillStyle = BS.ink;
  ctx.fillRect(64, 1420, 952, 3);
  ctx.font = "900 54px " + HEAVY;
  ctx.fillStyle = BS.ink;
  const sub = wrap(ctx, String(beat.text), 900).slice(0, 2);
  sub.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, 1470 + i * 60);
  });
  ctx.fillRect(64, 1560, 952, 1);
  ctx.font = "400 20px " + LIGHT;
  ctx.fillStyle = BS.gray;
  const end = "\u2014 \u672A \u5B8C \u5F85 \u7EED \u2014";
  ctx.fillText(end, (W - ctx.measureText(end).width) / 2, 1650);
}
var CV = { paper: "#EDE6DA", ink: "#141414", blue: "#2B3CFF", white: "#FFFFFF" };
function drawCover(ctx, beat, t, index, _total, layout = "auto") {
  if (layout === "big") beat = { ...beat, card: "hook" };
  if (layout === "content" && beat.card === "stat") beat = { ...beat, value: "" };
  ctx.fillStyle = CV.paper;
  ctx.fillRect(0, 0, W, H);
  ctx.font = "900 150px " + HEAVY;
  ctx.fillStyle = CV.ink;
  ctx.fillText("\u8001  \u677F", 52, 196);
  ctx.font = "400 24px " + LIGHT;
  const issue = `NO.${String(index + 1).padStart(2, "0")} / 2026`;
  ctx.fillText(issue, 1016 - ctx.measureText(issue).width, 176);
  ctx.fillStyle = CV.ink;
  ctx.fillRect(56, 216, 960, 1);
  const cvNum = String(beat.value || "").replace(/[^\d.]/g, "");
  if (cvNum && beat.card === "stat") {
    const pp = ease(t / 0.5);
    ctx.save();
    ctx.translate(540, 700);
    ctx.rotate(-2 * Math.PI / 180);
    ctx.fillStyle = CV.blue;
    ctx.fillRect(-450, -280 * pp, 900, 560 * pp);
    ctx.restore();
    ctx.font = "900 300px " + HEAVY;
    ctx.fillStyle = CV.paper;
    const shown = String(Math.round(Number(cvNum) * Math.min(1, t / 0.5)));
    ctx.fillText(shown, 96, 800);
    ctx.font = "900 64px " + HEAVY;
    ctx.fillText(beat.unit || "", 100 + ctx.measureText(shown).width + 20, 790);
    ctx.font = "400 26px " + LIGHT;
    ctx.fillStyle = CV.ink;
    ctx.fillText((beat.label || "").slice(0, 18), 100, 900);
    return;
  }
  const p = ease(t / 0.5);
  ctx.save();
  ctx.translate(540, 700);
  ctx.rotate(-2 * Math.PI / 180);
  ctx.fillStyle = CV.blue;
  ctx.fillRect(-450, -280 * p, 900, 560 * p);
  ctx.restore();
  ctx.fillStyle = CV.paper;
  ctx.beginPath();
  ctx.arc(540, 640, 210 * p, 0, Math.PI * 2);
  ctx.fill();
  ctx.font = "400 28px " + LIGHT;
  ctx.fillStyle = CV.ink;
  const sides = ["\u56DE\u672C\u6A21\u578B", "316 \u5BB6\u5E97", "\u52A0\u76DF\u771F\u76F8"];
  sides.forEach((s, i) => {
    ctx.save();
    ctx.translate(1008, 340 + i * 190);
    ctx.rotate(Math.PI / 2);
    ctx.fillText(s, 0, 0);
    ctx.restore();
  });
  ctx.font = "900 96px " + HEAVY;
  ctx.fillStyle = CV.ink;
  const title = wrap(ctx, beat.title || beat.topic || beat.text, 940).slice(0, 2);
  title.forEach((ln, i) => ctx.fillText(ln, 44, 1070 + i * 104));
  ctx.fillStyle = CV.white;
  ctx.fillRect(780, 1290, 200, 110);
  ctx.save();
  ctx.fillStyle = CV.ink;
  let x = 792;
  let seed = 7;
  while (x < 968) {
    seed = (seed * 1103515245 + 12345) % 2147483647;
    const w = 1 + seed % 5;
    ctx.fillRect(x, 1300, w, 80);
    x += w + 2 + (seed >> 8) % 4;
  }
  ctx.restore();
  ctx.font = "400 16px " + LIGHT;
  ctx.fillStyle = CV.ink;
  ctx.fillText("9 771234 567003", 782, 1394);
  ctx.strokeStyle = CV.ink;
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.arc(150, 1330, 62, 0, Math.PI * 2);
  ctx.stroke();
  ctx.font = "900 22px " + HEAVY;
  ctx.fillStyle = CV.ink;
  ["\u672C\u671F\u9644\u8D60", "\u53E3\u64AD\u6A21\u677F", "3 \u5957"].forEach((s, i) => ctx.fillText(s, 106, 1318 + i * 28));
  ctx.fillStyle = CV.ink;
  ctx.fillRect(0, 1420, W, 160);
  ctx.fillStyle = CV.blue;
  ctx.fillRect(0, 1416, W, 4);
  ctx.font = "900 56px " + HEAVY;
  ctx.fillStyle = CV.paper;
  const sub = wrap(ctx, String(beat.text), 900).slice(0, 2);
  sub.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W - w) / 2, 1490 + i * 62);
  });
}
var NEW_STYLES = {
  newsroom: drawNewsroom,
  marker: drawMarker,
  swiss: drawSwiss,
  broadsheet: drawBroadsheet,
  cover: drawCover
};

// app/src/lib/draw.ts
var W2 = 1080;
var H2 = 1920;
var FPS = 30;
var HEAVY2 = '"Microsoft YaHei","PingFang SC","Noto Sans SC",sans-serif';
var ease2 = (x) => 1 - Math.pow(1 - Math.min(1, Math.max(0, x)), 3);
function wrapText(ctx, text, maxWidth) {
  const lines = [];
  let line = "";
  for (const ch of text) {
    const next = line + ch;
    if (ctx.measureText(next).width > maxWidth && line) {
      lines.push(line);
      line = ch;
    } else {
      line = next;
    }
  }
  if (line) lines.push(line);
  return lines;
}
function drawBackground(ctx, pal) {
  const g = ctx.createLinearGradient(0, 0, W2, H2);
  g.addColorStop(0, pal.bg1);
  g.addColorStop(1, pal.bg2);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, W2, H2);
  const glow = ctx.createRadialGradient(W2 * 0.15, H2 * 0.05, 0, W2 * 0.15, H2 * 0.05, 950);
  glow.addColorStop(0, pal.glow);
  glow.addColorStop(1, "rgba(0,0,0,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, W2, H2);
}
function drawChrome(ctx, pal, index, total, topic) {
  ctx.save();
  ctx.font = `700 26px ${HEAVY2}`;
  ctx.fillStyle = pal.dark ? pal.ink : pal.ink;
  ctx.globalAlpha = 0.62;
  ctx.fillText("GETCUT", 64, 80);
  ctx.fillStyle = pal.accent;
  ctx.fillText("\xB7", 64 + ctx.measureText("GETCUT").width + 6, 80);
  ctx.fillStyle = pal.ink;
  ctx.fillText("\u83B7\u5BA2\u7247", 64 + ctx.measureText("GETCUT\xB7").width + 16, 80);
  ctx.globalAlpha = 1;
  if (topic) {
    ctx.font = `700 40px ${HEAVY2}`;
    ctx.fillStyle = pal.accent;
    ctx.fillRect(64, 150, 78, 52);
    ctx.fillStyle = pal.accentInk;
    ctx.fillText(String(index + 1).padStart(2, "0"), 78, 187);
    ctx.fillStyle = pal.ink;
    ctx.fillText(topic, 162, 188);
  }
  ctx.font = `400 24px ${HEAVY2}`;
  ctx.fillStyle = pal.muted;
  const page = `${index + 1} / ${total}`;
  ctx.fillText(page, W2 - 64 - ctx.measureText(page).width, 80);
  ctx.fillStyle = pal.hairline;
  ctx.fillRect(64, 218, W2 - 128, 3);
  ctx.fillStyle = pal.accent;
  ctx.fillRect(64, 218, (W2 - 128) * (index + 1) / total, 3);
  ctx.restore();
}
function drawSubtitle(ctx, text) {
  ctx.save();
  ctx.font = `700 52px ${HEAVY2}`;
  const lines = wrapText(ctx, text, 880);
  const lineH = 70;
  const boxH = lines.length * lineH + 24;
  ctx.fillStyle = "rgba(0,0,0,0.55)";
  ctx.fillRect(60, H2 - 200 - boxH, W2 - 120, boxH);
  ctx.fillStyle = "#ffffff";
  lines.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W2 - w) / 2, H2 - 200 - boxH + 58 + i * lineH);
  });
  ctx.restore();
}
function drawBottom(ctx, pal) {
  ctx.save();
  ctx.font = `400 22px ${HEAVY2}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText("GETCUT \xB7 \u83B7\u5BA2\u7247", 64, H2 - 70);
  const tag = "#\u83B7\u5BA2 #\u672C\u5730\u751F\u610F";
  ctx.fillText(tag, W2 - 64 - ctx.measureText(tag).width, H2 - 70);
  ctx.restore();
}
function drawRichText(ctx, text, x, y, pal, color) {
  const parts = text.split(/(\d+(?:\.\d+)?\s*(?:万|亿|%|元|块|天|年|个月|倍|件|人|分)?)/);
  let cx = x;
  for (let i = 0; i < parts.length; i++) {
    const seg = parts[i];
    if (!seg) continue;
    ctx.fillStyle = i % 2 === 1 ? pal.accent : color;
    ctx.fillText(seg, cx, y);
    cx += ctx.measureText(seg).width;
  }
}
function cardHook(ctx, beat, t, pal) {
  const p = ease2(t / 0.45);
  ctx.font = `700 30px ${HEAVY2}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText("\u83B7\u5BA2 \xB7 \u4E00\u5206\u949F\u8BF4\u6E05", 96, 520);
  ctx.font = `900 112px ${HEAVY2}`;
  const lines = wrapText(ctx, beat.title || beat.text, 880);
  lines.forEach((ln, i) => {
    ctx.save();
    ctx.globalAlpha = ease2((t - 0.1 * i) / 0.45);
    ctx.fillStyle = pal.ink;
    ctx.fillText(ln, 96, 680 + i * 132 + (1 - p) * 26);
    ctx.restore();
  });
  ctx.fillStyle = pal.accent;
  ctx.fillRect(96, 700 + (lines.length - 1) * 132, 260 * p, 10);
}
function cardPlain(ctx, beat, t, pal) {
  const words = beat.text.split(/[，。！？；、,.;!?]/).map((s) => s.trim()).filter((s) => s.length >= 2).slice(0, 3);
  ctx.font = `900 72px ${HEAVY2}`;
  words.forEach((w, i) => {
    const p = ease2((t - i * 0.18) / 0.4);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;
    ctx.translate((1 - p) * -26, 0);
    ctx.fillStyle = pal.accent;
    ctx.fillRect(96, 700 + i * 130, 12, 12);
    drawRichText(ctx, w, 132, 726 + i * 130, pal, pal.ink);
    ctx.restore();
  });
}
function cardStat(ctx, beat, t, pal) {
  ctx.font = `400 30px ${HEAVY2}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText("\u6570\u636E", 96, 540);
  const num = Number(String(beat.value || "").replace(/[^\d.]/g, ""));
  const shown = Number.isFinite(num) ? Math.round(num * Math.min(1, t / 0.6)) : beat.value;
  ctx.font = `900 260px ${HEAVY2}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText(String(shown), 90, 820);
  const numW = ctx.measureText(String(shown)).width;
  ctx.font = `900 84px ${HEAVY2}`;
  ctx.fillStyle = pal.ink;
  ctx.fillText(beat.unit || "", 90 + numW + 14, 810);
  ctx.fillStyle = pal.hairline;
  ctx.fillRect(96, 880, 620, 3);
  ctx.font = `400 48px ${HEAVY2}`;
  ctx.fillStyle = pal.muted;
  if (beat.label) ctx.fillText(wrapText(ctx, beat.label, 820)[0], 96, 950);
  const bars = [0.42, 0.68, 1];
  bars.forEach((h, i) => {
    const bp = ease2((t - 0.1 - i * 0.08) / 0.5);
    ctx.fillStyle = i === 2 ? pal.accent : pal.hairline;
    ctx.fillRect(96 + i * 90, 1140 - 200 * h * bp, 66, 200 * h * bp);
  });
}
function cardList(ctx, beat, t, pal) {
  const items = (beat.items?.length ? beat.items : beat.text.split(/[、，,；;]/)).filter(Boolean).slice(0, 4);
  ctx.font = `900 56px ${HEAVY2}`;
  items.forEach((item, i) => {
    const p = ease2((t - i * 0.2) / 0.4);
    if (p <= 0) return;
    ctx.save();
    ctx.globalAlpha = p;
    const y = 560 + i * 150;
    ctx.fillStyle = i === 0 ? pal.accent : "rgba(255,255,255,0.08)";
    ctx.fillRect(96, y - 46, 56, 56);
    ctx.fillStyle = i === 0 ? pal.accentInk : pal.muted;
    ctx.font = `700 26px ${HEAVY2}`;
    ctx.fillText(String(i + 1).padStart(2, "0"), 108, y - 8);
    ctx.font = `900 56px ${HEAVY2}`;
    const lines = wrapText(ctx, item, 760);
    lines.slice(0, 2).forEach((ln, k) => {
      drawRichText(ctx, ln, 186, y + k * 72, pal, pal.ink);
    });
    ctx.restore();
  });
}
function cardCompare(ctx, beat, t, pal) {
  const p = ease2(t / 0.45);
  const panels = [
    { head: "\u522B\u4EBA", body: beat.left || "", hot: false },
    { head: "\u6211\u4EEC", body: beat.right || "", hot: true }
  ];
  panels.forEach((pn, i) => {
    const x = 80 + i * 470;
    ctx.save();
    ctx.globalAlpha = ease2((t - i * 0.12) / 0.4);
    ctx.fillStyle = pn.hot ? pal.panel : "rgba(0,0,0,0.18)";
    ctx.fillRect(x, 470, 440, 620);
    ctx.strokeStyle = pn.hot ? pal.accent : pal.hairline;
    ctx.lineWidth = 3;
    ctx.strokeRect(x, 470, 440, 620);
    ctx.font = `700 26px ${HEAVY2}`;
    ctx.fillStyle = pn.hot ? pal.accent : pal.muted;
    ctx.fillText(pn.head, x + 32, 530);
    ctx.font = `900 56px ${HEAVY2}`;
    wrapText(ctx, pn.body, 380).slice(0, 4).forEach((ln, k) => {
      drawRichText(ctx, ln, x + 32, 610 + k * 74, pal, pal.ink);
    });
    ctx.restore();
  });
  ctx.save();
  ctx.globalAlpha = Math.min(1, p * 1.3);
  ctx.fillStyle = pal.accent;
  ctx.beginPath();
  ctx.arc(W2 / 2, 780, 58, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillStyle = pal.accentInk;
  ctx.font = `900 36px ${HEAVY2}`;
  ctx.fillText("VS", W2 / 2 - 28, 794);
  ctx.restore();
}
function cardQuote(ctx, beat, t, pal) {
  const p = ease2(t / 0.5);
  ctx.save();
  ctx.globalAlpha = 0.25;
  ctx.font = `900 260px ${HEAVY2}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText("\u201C", 80, 700);
  ctx.restore();
  ctx.font = `900 92px ${HEAVY2}`;
  const lines = wrapText(ctx, beat.title || beat.text, 860);
  ctx.save();
  ctx.globalAlpha = p;
  ctx.translate((1 - p) * -26, 0);
  lines.slice(0, 4).forEach((ln, i) => {
    drawRichText(ctx, ln, 96, 780 + i * 118, pal, pal.ink);
  });
  ctx.restore();
}
function cardCta(ctx, beat, t, pal) {
  const p = ease2(t / 0.45);
  ctx.save();
  ctx.globalAlpha = p;
  ctx.translate(0, (1 - p) * 30);
  ctx.fillStyle = pal.accent;
  const boxH = 320;
  ctx.fillRect(80, 600, W2 - 160, boxH);
  ctx.fillStyle = pal.accentInk;
  ctx.font = `900 72px ${HEAVY2}`;
  const lines = wrapText(ctx, beat.cta || beat.title || beat.text, 820).slice(0, 2);
  lines.forEach((ln, i) => {
    const w = ctx.measureText(ln).width;
    ctx.fillText(ln, (W2 - w) / 2, 720 + i * 92);
  });
  ctx.restore();
  ctx.save();
  ctx.globalAlpha = ease2((t - 0.25) / 0.4);
  ctx.font = `400 32px ${HEAVY2}`;
  ctx.fillStyle = pal.ink;
  const pills = ["\u79C1\u4FE1", "\u8BC4\u8BBA", "\u5230\u5E97\u54A8\u8BE2"];
  let x = 170;
  pills.forEach((s) => {
    const w = ctx.measureText(s).width + 56;
    ctx.strokeStyle = pal.hairline;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.roundRect(x, 980, w, 74, 37);
    ctx.stroke();
    ctx.fillText(s, x + 28, 1028);
    x += w + 18;
  });
  ctx.restore();
}
function cardIntro(ctx, beat, t, pal) {
  const p = ease2(t / 0.5);
  ctx.save();
  ctx.globalAlpha = p;
  ctx.textAlign = "center";
  ctx.font = `900 44px ${HEAVY2}`;
  ctx.fillStyle = pal.accent;
  ctx.fillText("GETCUT", W2 / 2, 700);
  ctx.font = `400 26px ${HEAVY2}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText("\u672C\u673A\u51FA\u7247 \xB7 \u4E00\u5206\u949F\u8BF4\u6E05", W2 / 2, 748);
  ctx.font = `900 84px ${HEAVY2}`;
  ctx.fillStyle = pal.ink;
  const lines = wrapText(ctx, beat.title || beat.text, 860);
  lines.slice(0, 3).forEach((ln, i) => ctx.fillText(ln, W2 / 2, 900 + i * 104));
  ctx.fillStyle = pal.accent;
  ctx.fillRect(W2 / 2 - 90, 900 + lines.length * 104, 180, 6);
  ctx.restore();
}
function cardChapter(ctx, beat, t, pal) {
  const p = ease2(t / 0.45);
  ctx.save();
  ctx.textAlign = "center";
  ctx.globalAlpha = p;
  ctx.font = `900 260px ${HEAVY2}`;
  ctx.strokeStyle = pal.accent;
  ctx.lineWidth = 4;
  ctx.strokeText(String(beat.value || "1").padStart(2, "0"), W2 / 2, 760);
  ctx.font = `400 28px ${HEAVY2}`;
  ctx.fillStyle = pal.muted;
  ctx.fillText(`\u7B2C ${String(beat.value || "1").padStart(2, "0")} \u90E8\u5206`, W2 / 2, 830);
  ctx.font = `900 92px ${HEAVY2}`;
  ctx.fillStyle = pal.ink;
  wrapText(ctx, beat.topic || beat.title || "", 860).slice(0, 2).forEach((ln, i) => ctx.fillText(ln, W2 / 2, 960 + i * 110));
  ctx.fillStyle = pal.accent;
  ctx.fillRect(W2 / 2 - 110, 1090, 220, 8);
  ctx.restore();
}
var CARDS = {
  hook: cardHook,
  plain: cardPlain,
  stat: cardStat,
  list: cardList,
  compare: cardCompare,
  quote: cardQuote,
  cta: cardCta,
  intro: cardIntro,
  chapter: cardChapter
};
function isCoverCard(c) {
  return c === "intro" || c === "chapter";
}
function drawFrame(ctx, beat, t, theme, index, total, layout = "auto") {
  const special = NEW_STYLES[theme];
  if (special) {
    special(ctx, beat, t, index, total, layout);
    return;
  }
  if (layout === "big" && !isCoverCard(beat.card)) beat = { ...beat, card: "quote" };
  if (layout === "data" && (beat.value || beat.card === "stat")) beat = { ...beat, card: "stat" };
  if (layout === "content" && beat.card === "quote") beat = { ...beat, card: "plain" };
  const pal = PALETTES[theme];
  ctx.save();
  drawBackground(ctx, pal);
  const isCover = beat.card === "intro" || beat.card === "chapter";
  if (!isCover && beat.bg) {
    const img = beat.bg;
    const scale = Math.max(W2 / img.width, H2 / img.height);
    const dw = img.width * scale;
    const dh = img.height * scale;
    ctx.drawImage(img, (W2 - dw) / 2, (H2 - dh) / 2, dw, dh);
    ctx.fillStyle = pal.dark ? "rgba(0,0,0,0.72)" : "rgba(255,255,255,0.8)";
    ctx.fillRect(0, 0, W2, H2);
    const veil = ctx.createLinearGradient(0, 0, 0, H2);
    veil.addColorStop(0, "rgba(0,0,0,0.35)");
    veil.addColorStop(0.45, "rgba(0,0,0,0)");
    veil.addColorStop(1, "rgba(0,0,0,0.45)");
    ctx.fillStyle = veil;
    ctx.fillRect(0, 0, W2, H2);
  }
  if (isCover) {
    CARDS[beat.card](ctx, beat, t, pal);
  } else {
    drawChrome(ctx, pal, index, total, beat.topic);
    const push = 1 + 0.03 * Math.min(1, t / Math.max(0.5, beat.duration));
    ctx.translate(W2 / 2, H2 / 2);
    ctx.scale(push, push);
    ctx.translate(-W2 / 2, -H2 / 2);
    CARDS[beat.card]?.(ctx, beat, t, pal);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    const speaks = ["hook", "quote", "cta", "list", "plain"].includes(beat.card);
    if (!speaks) drawSubtitle(ctx, beat.text);
    drawBottom(ctx, pal);
  }
  ctx.restore();
}
export {
  FPS,
  H2 as H,
  W2 as W,
  drawFrame
};
