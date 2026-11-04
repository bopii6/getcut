export type CardKind =
  | 'hook' | 'plain' | 'stat' | 'list' | 'compare' | 'quote' | 'cta' | 'intro' | 'chapter';

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
  duration: number;
  audio?: AudioBuffer;
};

export type PlanBeat = Omit<Beat, 'duration' | 'audio'>;

export type ThemeName = 'poster' | 'magazine' | 'dashboard';
