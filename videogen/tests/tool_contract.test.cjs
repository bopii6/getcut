'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const tool = fs.readFileSync(
  path.join(__dirname, '..', 'renderer', 'src', 'tool', 'index.tsx'),
  'utf8',
);
const css = fs.readFileSync(
  path.join(__dirname, '..', 'renderer', 'src', 'tool', 'ui.css'),
  'utf8',
);

test('成片台保留手机端完成态、下载和内嵌播放', () => {
  assert.match(tool, /setPhase\('done'\)/);
  assert.match(tool, /setPrepMsg\('成片已生成'\)/);
  assert.match(tool, /<video src=\{finalUrl\} controls autoPlay playsInline preload="metadata" \/>/);
  assert.match(tool, /className="btn mobile-download" href=\{finalUrl\} download=\{fileName\}/);
  assert.match(css, /\.body\.handheld-focus \.pane\.right \{ order: -1;/);
  assert.match(css, /\.mobile-download \{ display: flex;/);
});

test('成片台预览声音开关和真实浏览器成片音频保持开启', () => {
  assert.match(tool, /const \[previewMuted, setPreviewMuted\]/);
  assert.match(tool, /muted=\{previewMuted\}/);
  assert.match(tool, /点这里打开声音/);
  assert.match(tool, /muted: false/);
  assert.match(tool, /电脑已领取，正在生成/);
});
