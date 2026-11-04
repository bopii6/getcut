import type { ThemeName } from './types';

export type Palette = {
  bg1: string; bg2: string; glow: string;
  ink: string; muted: string;
  accent: string; accentInk: string;
  hairline: string; panel: string; panelEdge: string;
  dark: boolean;
};

export const PALETTES: Record<ThemeName, Palette> = {
  poster: {
    bg1: '#080807', bg2: '#17130d',
    glow: 'rgba(255,212,0,0.20)',
    ink: '#f7f2e6', muted: 'rgba(247,242,230,0.55)',
    accent: '#ffd400', accentInk: '#0a0906',
    hairline: 'rgba(247,242,230,0.16)', panel: 'rgba(247,242,230,0.06)',
    panelEdge: 'rgba(255,212,0,0.45)', dark: true,
  },
  magazine: {
    bg1: '#f6f2e9', bg2: '#e9e1d2',
    glow: 'rgba(192,57,43,0.16)',
    ink: '#14100c', muted: 'rgba(20,16,12,0.55)',
    accent: '#c0392b', accentInk: '#fff8f2',
    hairline: 'rgba(20,16,12,0.16)', panel: 'rgba(255,255,255,0.6)',
    panelEdge: 'rgba(192,57,43,0.4)', dark: false,
  },
  dashboard: {
    bg1: '#06101f', bg2: '#0b1b2e',
    glow: 'rgba(64,169,255,0.22)',
    ink: '#e9f2ff', muted: 'rgba(233,242,255,0.55)',
    accent: '#40a9ff', accentInk: '#04121f',
    hairline: 'rgba(233,242,255,0.16)', panel: 'rgba(233,242,255,0.06)',
    panelEdge: 'rgba(64,169,255,0.5)', dark: true,
  },
};
