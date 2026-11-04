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
  news: {
    bg1: '#f7f5f2', bg2: '#e6e2dc',
    glow: 'rgba(214,40,40,0.14)',
    ink: '#141414', muted: 'rgba(20,20,20,0.55)',
    accent: '#d62828', accentInk: '#fff7f4',
    hairline: 'rgba(20,20,20,0.18)', panel: 'rgba(255,255,255,0.7)',
    panelEdge: 'rgba(214,40,40,0.45)', dark: false,
  },
  newsroom: {
    bg1: '#0C1B2A', bg2: '#0C1B2A',
    glow: 'rgba(216,35,42,0.16)',
    ink: '#FFFFFF', muted: 'rgba(255,255,255,0.55)',
    accent: '#D8232A', accentInk: '#FFFFFF',
    hairline: 'rgba(255,255,255,0.16)', panel: 'rgba(16,35,58,0.92)',
    panelEdge: 'rgba(44,90,142,0.8)', dark: true,
  },
  ledger: {
    bg1: '#08090A', bg2: '#08090A',
    glow: 'rgba(200,255,0,0.12)',
    ink: '#F2F3F5', muted: 'rgba(242,243,245,0.55)',
    accent: '#C8FF00', accentInk: '#08090A',
    hairline: '#23262B', panel: 'rgba(255,255,255,0.04)',
    panelEdge: '#2E3238', dark: true,
  },
  night: {
    bg1: '#0b0a16', bg2: '#161232',
    glow: 'rgba(124,108,255,0.25)',
    ink: '#ece9ff', muted: 'rgba(236,233,255,0.55)',
    accent: '#a78bfa', accentInk: '#120c26',
    hairline: 'rgba(236,233,255,0.16)', panel: 'rgba(236,233,255,0.06)',
    panelEdge: 'rgba(167,139,250,0.5)', dark: true,
  },
};

