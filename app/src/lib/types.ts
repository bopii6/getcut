export type CardKind =
  | 'hook' | 'plain' | 'stat' | 'list' | 'compare' | 'quote' | 'cta' | 'intro' | 'chapter';

export type ThemeName = 'poster' | 'magazine' | 'dashboard' | 'news' | 'night' | 'newsroom' | 'ledger' | 'marker' | 'swiss' | 'terminal' | 'broadsheet' | 'cover' | 'reel';

export type Beat = {
  text: string;
  card: CardKind;
  topic?: string;
  title?: string;
  value?: string;
  unit?: string;
  label?: string;
  items?: string[];
  left?: string;
  right?: string;
  cta?: string;
  broll?: string;
  bg?: HTMLCanvasElement | null;
  duration: number;
  audio?: AudioBuffer;
};

export type PlanBeat = Omit<Beat, 'duration' | 'audio' | 'bg'>;



