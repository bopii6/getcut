const api = require('../../utils/api.js');

const THEMES = [
  { id: 'poster', name: '黑金', desc: '一屏一句，观点型', color: '#ffd400' },
  { id: 'magazine', name: '纸感', desc: '暖纸底红章，知识型', color: '#c0392b' },
  { id: 'dashboard', name: '面板', desc: '深蓝数字，测评型', color: '#40a9ff' },
];

const MIN_CHARS = 8;
const MAX_CHARS = 1200;

Page({
  data: {
    text: '',
    counter: '0 / ' + MAX_CHARS,
    themes: THEMES,
    theme: 'poster',
    submitting: false,
    canGo: false,
    hint: '',
  },

  onInput(e) {
    const text = e.detail.value;
    const len = text.trim().length;
    let hint = '';
    if (len > 0 && len < MIN_CHARS) hint = `再写 ${MIN_CHARS - len} 个字才能拆出分镜`;
    if (len >= MAX_CHARS) hint = '到上限了，再长一条片要渲很久';

    this.setData({
      text,
      counter: `${len} / ${MAX_CHARS}`,
      canGo: len >= MIN_CHARS,
      hint,
    });
  },

  pickTheme(e) {
    this.setData({ theme: e.currentTarget.dataset.id });
  },

  async onGenerate() {
    if (this.data.submitting || !this.data.canGo) return;

    this.setData({ submitting: true, hint: '' });
    try {
      const job = await api.createJob({
        text: this.data.text.trim(),
        theme: this.data.theme,
        title: this.buildTitle(),
      });
      wx.navigateTo({ url: `/pages/result/result?id=${job.id}` });
    } catch (err) {
      this.setData({ hint: err.message || '建任务失败' });
    } finally {
      // 回来时按钮要能再点，不能一直转
      this.setData({ submitting: false });
    }
  },

  /** 拿第一句当片头标题，超过 14 字截断——太长会挤出画面。 */
  buildTitle() {
    const first = this.data.text
      .trim()
      .split(/[。！？!?；;\n]/)
      .map((s) => s.trim())
      .filter(Boolean)[0] || '';
    return first.slice(0, 14);
  },
});
