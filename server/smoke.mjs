// 冒烟测试：走完整条链路，出一条短片。
// 有章节标签的镜头会被自动插进章节页，所以这里故意分了三个 topic。
import { renderVideo } from './render.mjs';

const beats = [
  {
    card: 'hook',
    text: '开一家餐饮店，先别急着交定金',
    title: '别急着交定金',
    topic: '选址',
  },
  {
    card: 'stat',
    text: '总部说的日均一百二十单，你先打个七折',
    value: '120',
    unit: '单',
    label: '总部承诺的日均单量',
    topic: '算账',
  },
  {
    card: 'list',
    text: '这三笔钱，加盟前一定要问清楚',
    items: ['三十八万之外还有保证金', '装修必须用指定施工队', '食材比市场贵两成'],
    topic: '看合同',
  },
  {
    card: 'cta',
    text: '想开店的话，把城市和预算发给我',
    cta: '想开店？私信我算一笔账',
    topic: '看合同',
  },
];

const result = await renderVideo({
  beats,
  theme: process.env.THEME || 'poster',
  title: '三个数，看穿加盟套路',
  outFile: process.env.OUT || 'out/smoke.mp4',
  onProgress: (p) => {
    process.stdout.write(`\r  ${p.stage} · ${p.percent}%          `);
  },
});

console.log('\n✓ 出片完成');
console.log(result);
