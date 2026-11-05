export type ThemeName = 'magazine' | 'poster' | 'dashboard' | 'cartoon';

export type Theme = ReturnType<typeof themeOf>;

export function themeOf(name: ThemeName) {
  const base = {
    heavy: "'GC Heavy', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    light: "'GC Light', 'PingFang SC', 'Microsoft YaHei', sans-serif",
    // 关键词高亮：数字、金额、百分比会换成这个颜色
    accentInk: '#ffffff',
    music: 'music/cinematic.mp3',
    blobA: 'rgba(192,57,43,0.20)',
    blobB: 'rgba(214,178,120,0.22)',
    dark: false,
  };

  if (name === 'poster') {
    return {
      ...base,
      music: 'music/breakbeat.mp3',
      blobA: 'rgba(255,212,0,0.22)',
      blobB: 'rgba(255,140,0,0.14)',
      dark: true,
      bg: '#080807',
      glow: 'radial-gradient(900px 620px at 15% 0%, rgba(255,212,0,0.20), transparent 62%), radial-gradient(700px 500px at 100% 100%, rgba(255,212,0,0.08), transparent 60%)',
      texture: 'repeating-linear-gradient(0deg, rgba(255,255,255,0.035) 0px, rgba(255,255,255,0.035) 1px, transparent 1px, transparent 4px)',
      ink: '#f7f2e6',
      muted: 'rgba(247,242,230,0.52)',
      accent: '#ffd400',
      accentInk: '#0a0906',
      hairline: 'rgba(247,242,230,0.16)',
      panel: 'rgba(247,242,230,0.05)',
      panelEdge: 'rgba(255,212,0,0.45)',
    };
  }
  if (name === 'dashboard') {
    return {
      ...base,
      music: 'music/chill.mp3',
      blobA: 'rgba(64,169,255,0.24)',
      blobB: 'rgba(0,255,200,0.12)',
      dark: true,
      bg: '#06101f',
      glow: 'radial-gradient(900px 640px at 88% 6%, rgba(64,169,255,0.20), transparent 62%), radial-gradient(700px 520px at 0% 100%, rgba(64,169,255,0.10), transparent 60%)',
      texture: 'linear-gradient(rgba(255,255,255,0.045) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px)',
      ink: '#e9f2ff',
      muted: 'rgba(233,242,255,0.55)',
      accent: '#40a9ff',
      accentInk: '#04121f',
      hairline: 'rgba(233,242,255,0.16)',
      panel: 'rgba(233,242,255,0.06)',
      panelEdge: 'rgba(64,169,255,0.5)',
    };
  }
  if (name === 'cartoon') {
    return {
      ...base,
      music: 'music/breakbeat.mp3',
      blobA: 'rgba(226,74,40,0.12)',
      blobB: 'rgba(24,34,58,0.08)',
      dark: false,
      bg: '#f3ecdd',
      glow: 'radial-gradient(820px 620px at 82% 4%, rgba(226,74,40,0.16), transparent 62%), radial-gradient(680px 560px at 0% 100%, rgba(24,34,58,0.10), transparent 60%)',
      texture: 'repeating-radial-gradient(circle at 0 0, rgba(24,34,58,0.05) 0px, rgba(24,34,58,0.05) 1px, transparent 1px, transparent 3px)',
      ink: '#18223a',
      muted: 'rgba(24,34,58,0.55)',
      accent: '#e0542a',
      accentInk: '#fff8ee',
      hairline: 'rgba(24,34,58,0.16)',
      panel: 'rgba(255,253,247,0.92)',
      panelEdge: 'rgba(24,34,58,0.6)',
    };
  }
  return {
    ...base,
    bg: '#f4efe4',
    glow: 'radial-gradient(900px 620px at 82% 0%, rgba(192,57,43,0.14), transparent 60%), radial-gradient(700px 520px at 0% 100%, rgba(20,16,12,0.08), transparent 60%)',
    texture: 'repeating-radial-gradient(circle at 0 0, rgba(20,16,12,0.045) 0px, rgba(20,16,12,0.045) 1px, transparent 1px, transparent 3px)',
    ink: '#14100c',
    muted: 'rgba(20,16,12,0.55)',
    accent: '#c0392b',
    accentInk: '#fff8f2',
    hairline: 'rgba(20,16,12,0.16)',
    panel: 'rgba(255,255,255,0.6)',
    panelEdge: 'rgba(192,57,43,0.4)',
  };
}


