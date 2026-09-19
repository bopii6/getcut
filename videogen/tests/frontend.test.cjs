'use strict';

// Run: VIDEOGEN_TEST_DOM=<path-to-linkedom> node --test videogen/tests/frontend.test.cjs
// Production contract (server.py + server_static/index.html flow views):
//   /api/build keys: project_id, bundle, voice, bgm, sfx(bool), sfxMode,
//     subtitles(恒 true，界面无开关), sources, format, useLlm -> {job}
//     （series/disclaimer 已下线，前端不再传）
//   /api/job/:id stages: queued | named stage (stage8 1..8) | failed | done | unknown
//   Config lives in native <dialog> via [data-setting="style"|"sound"]; build button is #go.
const test = require('node:test');
const assert = require('node:assert/strict');
const {createHarness, deferred, project} = require('./frontend-harness.cjs');

async function setup(t, options) {
  const h = await createHarness(options);
  t.after(() => h.clean());
  return h;
}
const builds = h => h.requests.filter(r => r.url === '/api/build');
async function start(h) {
  h.respond('POST', '/api/build', {job: 'job-a'});
  await h.evaluate('startRender(CURB)');
  await h.flush();
}
// 设置直接摆在确认页上（模板/配音/音乐/音效），点渲染之前就能定
async function configure(h, {format, voice, sfx, sources, watermark, bgm}) {
  const wanted = [format, voice, sfx, sources, watermark, bgm].some(v => v !== undefined);
  if (!wanted) return;
  await h.flush(); // music select 的 onchange 在 /api/music 解析后才挂上
  if (format !== undefined) h.click('#fmt [data-v="' + format + '"]');
  if (voice !== undefined) h.click('#voiceSeg [data-v="' + voice + '"]');
  if (sfx !== undefined) h.click('#sfxSeg [data-v="' + sfx + '"]');
  if (sources !== undefined) h.click('.swt[data-k="sources"]');
  if (watermark !== undefined) h.click('.swt[data-k="watermark"]');
  if (bgm !== undefined) { h.get('bgm').value = bgm; h.get('bgm').onchange(); }
}

test('production boot loads templates and projects entirely through mocked fetch', async t => {
  const h = await setup(t);
  assert(h.get('topNew'), '顶栏必须常驻「新建项目」入口');
  assert.equal(h.evaluate('TPLS.length'), 6);
  assert(h.requests.some(r => r.url === '/api/templates'));
  assert(h.requests.some(r => r.url === '/api/projects'));
});

test('actual configuration controls serialize the exact production build payload', async t => {
  const h = await setup(t);
  await h.openProject();
  await configure(h, {format: 'data', voice: 'zh-CN-XiaoxiaoNeural',
    sfx: 'off', sources: false, bgm: 'assets/music/test.mp3'});
  h.respond('POST', '/api/build', {job: 'job-a'});
  await h.click('#go');
  await h.flush();
  assert.equal(builds(h).length, 1);
  // 节奏由服务端定死（1.1 倍）：请求体里不再有 rate
  assert.deepEqual(JSON.parse(builds(h)[0].body), {
    project_id: 'aa', bundle: 'bundle-a', voice: 'zh-CN-XiaoxiaoNeural',
    bgm: 'assets/music/test.mp3', sfx: false, sfxMode: 'off', subtitles: true,
    sources: false, watermark: true, format: 'data', useLlm: true
  });
  assert.equal(builds(h)[0].headers['Content-Type'], 'application/json');
  assert.equal(h.localStorage.getItem('vg.job.aa'), 'job-a');
});

test('节奏不给用户调：确认页上没有语速控件', async t => {
  const h = await setup(t);
  await h.openProject();
  assert.equal(h.document.querySelector('#rateSeg'), null, '语速选择器必须已下线');
  assert.equal(h.document.querySelector('#rateTxt'), null);
});

test('all sound effect modes preserve production sfx boolean semantics', async t => {
  for (const mode of ['off', 'all']) {
    const h = await setup(t);
    await h.openProject();
    await configure(h, {sfx: mode});
    await start(h);
    const payload = JSON.parse(builds(h)[0].body);
    assert.equal(payload.sfxMode, mode);
    assert.equal(payload.sfx, mode !== 'off');
  }
});

test('persisted configuration loads without reading real user storage', async t => {
  const h = await setup(t, {storage: {'vg.cfg': JSON.stringify({format: 'poster', voice: 'zh-CN-YunjianNeural'})}});
  await h.openProject();
  assert(h.document.querySelector('#fmt [data-v="poster"]').classList.contains('on'));
  assert(h.document.querySelector('#voiceSeg [data-v="zh-CN-YunjianNeural"]').classList.contains('on'));
});

test('malformed saved configuration safely falls back to defaults', async t => {
  const h = await setup(t, {storage: {'vg.cfg': '{bad-json'}});
  assert.equal(h.evaluate('CFG.format'), 'editorial');
  assert.equal(h.evaluate('CFG.sfxMode'), 'all');
  assert.equal(h.evaluate('CFG.rate'), undefined);
});

test('品牌水印默认开着，关掉之后渲染请求带 false', async t => {
  const h = await setup(t);
  await h.openProject();
  const swt = h.document.querySelector('.swt[data-k="watermark"]');
  assert(swt, '「更多设置」里要有品牌水印开关');
  assert(swt.classList.contains('on'), '默认是开的');
  await configure(h, {watermark: false});
  await start(h);
  const payload = JSON.parse(builds(h)[0].body);
  assert.equal(payload.watermark, false);
});

test('duplicate starts during submission and queued task issue just one POST', async t => {
  const h = await setup(t);
  await h.openProject();
  const reply = deferred();
  h.respond('POST', '/api/build', () => reply.promise);
  const first = h.evaluate('startRender(CURB)');
  const second = h.evaluate('startRender(CURB)');
  const pendingCount = builds(h).length;
  reply.resolve({job: 'job-a'});
  await Promise.all([first, second]); await h.flush();
  assert.equal(pendingCount, 1, 'Start guard must work before the build response');
  await h.evaluate('startRender(CURB)'); await h.flush();
  assert.equal(builds(h).length, 1, 'An active task must block another submission');
});

test('generation shows one plain progress bar, then the failure reason and a retry', async t => {
  const h = await setup(t);
  await h.openProject(); await start(h);
  assert.match(h.get('vg-bigline').textContent, /排队中/);
  h.jobStates.set('job-a', {project_id: 'aa', stage: 'render', stage8: 5, progress: 54,
    detail: '正在渲染画面 1,037 / 3,455 帧', elapsed: 40, error: null});
  await h.tick();
  assert.equal(h.get('vg-pct').textContent, '54%');
  assert.equal(h.get('vg-bigbar').querySelector('i').style.width, '54%');
  assert.match(h.get('vg-bigline').textContent, /正在渲染画面/);
  assert.equal(h.document.querySelectorAll('.vg-stage').length, 0, '生成页不再展示逐阶段细节');
  h.jobStates.set('job-a', {project_id: 'aa', stage: 'failed', stage8: 5, progress: 54,
    error: '素材包不存在或路径不合法'});
  await h.tick();
  assert.equal(h.get('vg-bigstage').textContent, '这一版没做成');
  assert.match(h.get('vg-bigline').textContent, /素材包已经不在服务器上了/, '失败要给可行动的人话');
  assert.equal(h.localStorage.getItem('vg.job.aa'), null);
  assert.equal(h.get('againBtn').disabled, false, '失败后要能重来');
  assert.equal([...h.timers.values()].filter(x => x.ms === 1500).length, 0, '轮询必须停');
});

test('completion puts the finished video right where the user waited, and the export view still works', async t => {
  const h = await setup(t);
  await h.openProject(); await start(h);
  h.jobStates.set('job-a', {project_id: 'aa', stage: 'render', stage8: 5, progress: 50});
  await h.tick();
  h.projects[0].renders = [{id: 'job-a', file: 'fixture-job-a.mp4', ts: '2026-01-01 12:00'}];
  h.projects[0].renders_count = 1;
  h.jobStates.set('job-a', {project_id: 'aa', stage: 'done', stage8: 8, progress: 100,
    video: 'fixture-job-a.mp4', elapsed: 300});
  await h.tick();
  assert.equal(h.get('vg-bigstage').textContent, '成片好了。');
  assert.equal(h.get('vg-pct').textContent, '100%');
  assert(h.get('mainPlayer'), '完成后要就地给出成片');
  assert.match(h.get('mainPlayer').getAttribute('src'), /\/video\/job-a/);
  assert.match(h.get('dlBtn').getAttribute('href'), /\/video\/job-a/);
  assert.equal(h.localStorage.getItem('vg.job.aa'), null);
  const exportBtn = h.get('vg-export');
  assert(exportBtn, 'Done state must expose the export entry');
  h.click('#vg-export');
  assert.match(h.get('mainPlayer').getAttribute('src'), /\/video\/job-a/);
  assert.equal(h.get('jyBtn').tagName, 'BUTTON', '导出剪映改成「一键导入」按钮，不再是下载链接');
  assert.equal(h.document.querySelectorAll('#hist [data-render="job-a"]').length, 1);
  h.click('#jyBtn');
  await h.flush();
  assert.equal(h.requests.filter(r => /jianying-status/.test(r.url)).length, 1, '进导出页要问一次草稿状态');
  assert.equal(h.requests.filter(r => /jianying-import/.test(r.url)).length, 1, '点按钮走「装进剪映」接口');
  assert.equal(h.requests.filter(r => /jianying-draft/.test(r.url)).length, 0, '装得进剪映就不用下载了');
  assert.match(h.get('jyBtn').textContent, /已导入/, '装好之后按钮给个明确回执');
});

test('装不进剪映时自动退回下载导入包，不让用户空手而归', async t => {
  const h = await setup(t);
  await h.openProject();
  await start(h);
  h.projects[0].renders = [{id: 'job-a', file: 'fixture-job-a.mp4', ts: '2026-01-01 12:00'}];
  h.projects[0].renders_count = 1;
  h.jobStates.set('job-a', {project_id: 'aa', stage: 'done', stage8: 8, progress: 100,
    video: 'fixture-job-a.mp4', elapsed: 300});
  await h.tick();
  h.respond('POST', '/api/projects/aa/renders/job-a/jianying-import', {installed: false, download: true});
  h.click('#vg-export');
  h.click('#jyBtn');
  await h.flush();
  assert.equal(h.requests.filter(r => /jianying-draft/.test(r.url)).length, 1, '装不进就要把导入包下载下来');
  h.clean();   // 这条链路上不能有未 mock 的请求、也不能有控制台报错
});

test('generation view keeps the decision before the render and shows no per-stage detail', async t => {
  const h = await setup(t);
  await h.openProject();
  assert(h.get('fmt'), '确认页要能直接选画面模板');
  assert(h.get('voiceSeg'), '确认页要能直接选配音');
  assert(h.get('bgm'), '确认页要能直接选背景音乐');
  assert(h.get('sfxSeg'), '确认页要能直接选音效');
  assert.equal(h.document.querySelectorAll('#fmt .tpl').length, 6, '模板要摆在页面上，不是弹窗里');
  // 确认页只确认不改稿：素材与文案收成一条状态，原文只在弹窗里看一眼
  assert.match(h.get('vg-view').textContent, /素材已读入/);
  assert.equal(h.document.querySelectorAll('#vg-view .vg-fulltext').length, 0, '文稿不应铺在页面上');
  assert(h.get('vg-peek'), '原包内容改成点开才看');
  // 模板只占一格：默认收起，点那一格才展开，选完自动收起并回填
  const grid = h.get('fmt');
  assert(grid.classList.contains('hide'), '模板列表默认收起，不占地方');
  assert.match(h.get('tplNow').textContent, new RegExp(h.evaluate('CFG.format')), '当前这套要能一眼看到');
  await h.click('#tplNow');
  assert(!grid.classList.contains('hide'), '点那一格要展开');
  assert.match(h.get('tplNow').textContent, /收起/, '展开了那一格要提示能收起');
  await h.click('#fmt [data-v="poster"]');
  assert(grid.classList.contains('hide'), '选完要自动收起');
  assert.equal(h.evaluate('CFG.format'), 'poster');
  assert.match(h.get('tplNow').textContent, /poster/, '那一格要换成新选的');
  assert.match(h.get('tplNow').textContent, /换一个/, '收起后要写回「换一个」');
  await start(h);
  h.jobStates.set('job-a', {project_id: 'aa', stage: 'tts', stage8: 2, progress: 10});
  await h.tick();
  assert.equal(h.get('vg-bigstage').textContent, '正在生成你的视频');
  assert.equal(h.get('vg-step').textContent, '第 2/8 步 · AI 配音', '进度条上要写清当前环节');
  h.jobStates.set('job-a', {project_id: 'aa', stage: 'render', stage8: 5, progress: 54});
  await h.tick();
  assert.equal(h.get('vg-step').textContent, '第 5/8 步 · 画面渲染', '环节要跟着任务走');
  assert.equal(h.document.querySelectorAll('#vg-stages, .vg-stage, .vg-artifact, .vg-progress').length, 0,
    '用户不需要逐阶段细节，只要一根总进度条');
});

test('build HTTP error restores submit button and creates no saved job', async t => {
  const h = await setup(t);
  await h.openProject();
  h.respond('POST', '/api/build', {__httpStatus: 409, body: {error: '该项目已有任务在排队/渲染，等它完成再发起新的'}});
  await h.evaluate('startRender(CURB)'); await h.flush();
  assert.equal(h.localStorage.getItem('vg.job.aa'), null);
  assert.match(h.document.body.textContent, /该项目已有任务/);
  assert(h.get('go'), 'Confirm view must be restored after conflict');
  assert.equal(h.get('go').disabled, false);
});

test('late bundle response cannot overwrite the newly selected project', async t => {
  const h = await setup(t);
  const reply = deferred();
  h.respond('GET', '/api/bundle/bundle-a', () => reply.promise);
  const pending = h.openProject(project());
  await h.flush();
  await h.openProject(project('bb', 'bundle-b'));
  reply.resolve(require('./frontend-harness.cjs').bundle('bundle-a'));
  await pending; await h.flush();
  assert.equal(h.evaluate('CUR.project_id'), 'bb');
  assert.equal(h.evaluate('CURB.name'), 'bundle-b', 'Old project bundle response must be ignored');
});

test('late route lookup cannot take navigation back to the prior project', async t => {
  const h = await setup(t);
  const reply = deferred();
  let first = true;
  h.respond('GET', '/api/projects', () => {
    if (first) { first = false; return reply.promise; }
    return h.projects;
  });
  const pending = h.evaluate('location.hash = "#/project/aa"; route(true)');
  await h.flush();
  await h.evaluate('location.hash = "#/project/bb"; route(true)');
  await h.flush();
  reply.resolve(h.projects);
  await pending; await h.flush();
  assert.equal(h.evaluate('CUR.project_id'), 'bb');
  assert.equal(h.evaluate('CURB.name'), 'bundle-b');
});

test('late build response saves the job against its originating project only', async t => {
  const h = await setup(t);
  await h.openProject();
  const reply = deferred();
  h.respond('POST', '/api/build', () => reply.promise);
  const pending = h.evaluate('startRender(CURB)');
  await h.openProject(project('bb', 'bundle-b'));
  reply.resolve({job: 'job-a'});
  await pending; await h.flush();
  assert.equal(h.localStorage.getItem('vg.job.aa'), 'job-a');
  assert.equal(h.localStorage.getItem('vg.job.bb'), null);
  assert.equal(h.evaluate('CUR.project_id'), 'bb');
  assert.equal(h.evaluate('FLOW && FLOW.jobId'), null, 'New project must not adopt the old job');
});

test('home lists one poster per project and shows how many versions exist', async t => {
  const h = await setup(t);
  h.projects[0].renders = [
    {id: 'job-a-old', file: 'old.mp4', ts: '2026-01-01 10:00'},
    {id: 'job-a', file: 'new.mp4', ts: '2026-01-02 10:00'},
  ];
  h.projects[0].renders_count = 2;
  h.projects[1].renders = [{id: 'job-b', file: 'b.mp4', ts: '2026-01-03 10:00'}];
  h.projects[1].renders_count = 1;
  await h.evaluate('renderHome()'); await h.flush();
  const posters = h.document.querySelectorAll('#posters .poster');
  assert.equal(posters.length, 2, 'Two projects with renders must produce two posters');
  const badges = h.document.querySelectorAll('#posters .pver');
  assert.equal(badges.length, 1, 'Only the project with several versions gets a version badge');
  assert.match(badges[0].textContent, /共 2 版/);
  const withBadge = [...posters].find(p => p.querySelector('.pver'));
  assert.match(withBadge.getAttribute ? withBadge.textContent : '', /Project aa/, 'Badge sits on the multi-version project');
  assert.match(await h.document.querySelector('#posters .poster video').getAttribute('src'), /\/video\//);
  assert.match(h.document.querySelector('.sec-h .n').textContent, /2 个项目 · 共 3 条成片/);
});

test('renaming a project saves through the ownership-checked mount endpoint', async t => {
  const h = await setup(t);
  h.respond('POST', '/api/projects/aa/mount', {ok: true});
  await h.evaluate('renderHome()'); await h.flush();
  assert(h.document.querySelector('.pcard [data-ren]'), 'Project cards must expose rename');
  await h.click('.pcard [data-ren]');
  const input = h.get('rnName');
  assert(input, 'Rename dialog must offer a name field');
  assert.equal(input.value, 'Project aa', 'Rename starts from the current title');
  input.value = '  新名字  ';
  await h.click('.modal .row [data-k]');
  await h.flush();
  const calls = h.requests.filter(r => r.url === '/api/projects/aa/mount');
  assert.equal(calls.length, 1, 'Rename must hit the project-scoped endpoint exactly once');
  assert.deepEqual(JSON.parse(calls[0].body), {bundle: 'bundle-a', title: '新名字'},
    'Rename keeps the mounted bundle and trims the new title');
  assert.equal(h.evaluate('HOME_PS[0].title'), '新名字');
  assert.equal(h.document.querySelector('.pcard .ct').textContent, '新名字');
  assert.equal(h.document.querySelectorAll('.modal').length, 0, 'Dialog closes after saving');
});

test('forgot-password asks for a code and submits the reset payload', async t => {
  const h = await setup(t);
  h.respond('GET', '/api/auth/status', {locked: true, smtp: false, dev_email: true, token_auth: false});
  h.respond('POST', '/api/auth/reset-code', {ok: true, message: '（本机开发模式）验证码：123456'});
  h.respond('POST', '/api/auth/reset', {email: 'someone@example.invalid'});
  await h.evaluate('showAuth()'); await h.flush();
  await h.click('.atabs button[data-m="login"]');
  assert(h.get('liForgot'), 'Login form must offer 忘记密码');
  await h.click('#liForgot');
  const email = h.get('rsEmail');
  assert(email && h.get('rsCode') && h.get('rsPass') && h.get('rsPass2'), 'Reset form must expose all fields');
  email.value = 'someone@example.invalid';
  await h.click('#rsSend');
  await h.flush();
  const sends = h.requests.filter(r => r.url === '/api/auth/reset-code');
  assert.equal(sends.length, 1, 'Reset code must not be requested twice');
  assert.deepEqual(JSON.parse(sends[0].body), {email: 'someone@example.invalid'});
  h.get('rsCode').value = '123456';
  h.get('rsPass').value = 'brand-new-pass';
  h.get('rsPass2').value = 'brand-new-pass';
  await h.click('#rsGo');
  await h.flush();
  const resets = h.requests.filter(r => r.url === '/api/auth/reset');
  assert.equal(resets.length, 1, 'Reset must be submitted exactly once');
  assert.deepEqual(JSON.parse(resets[0].body),
    {email: 'someone@example.invalid', code: '123456', password: 'brand-new-pass', remember: true});
});

test('late poll response cannot paint another project or clear its active task', async t => {
  const h = await setup(t);
  await h.openProject(); await start(h);
  h.localStorage.setItem('vg.job.bb', 'job-b');
  const reply = deferred();
  h.respond('GET', '/api/job/job-a', () => reply.promise);
  const pending = h.evaluate('pollJob("job-a")');
  await h.flush();
  await h.openProject(project('bb', 'bundle-b'));
  reply.resolve({project_id: 'aa', stage: 'failed', stage8: 5, progress: 44, error: 'obsolete failure'});
  await pending; await h.flush();
  assert.equal(h.localStorage.getItem('vg.job.bb'), 'job-b');
  assert.equal(h.evaluate('FLOW.status.stage'), 'queued', 'Project bb must keep its own live status');
  assert(!h.document.body.textContent.includes('obsolete failure'));
});

test('顶栏项目胶囊只在项目里已经有素材时出现，空项目不显示', async t => {
  const h = await setup(t);
  await h.openProject();  // 默认项目带 bundle-a，有素材
  assert(!h.get('switcher').classList.contains('hide'),
    '读到素材时要显示：项目名 + N 素材 + 切换项目才有内容可写');
  await h.openProject({...h.projects[0], bundle: null, title: '新建项目'});  // 刚建、还没读素材
  assert(h.get('switcher').classList.contains('hide'),
    '空项目里它只写得出「新建项目 / 尚未读取素材」，看着像个假按钮，必须藏起来');
});

test('档位与定价：顶栏「我的」入口带档位徽标，免费档先拦剪映导出并弹定价', async t => {
  const h = await setup(t);
  // 把当前用户降成免费档（harness 默认是高级版，方便老用例跑通）
  h.respond('GET', '/api/me', {email: 'offline@example.invalid', tier: 'free', tier_label: '免费版', is_admin: false,
    nickname: '创作者1234', avatar: '🐼', created: '2026-09-01',
    avatars: ['🦊', '🐼'], free_daily_builds: 2, builds_today: 1});
  await h.evaluate('ME = null; boot()'); await h.flush();
  assert(h.get('meBtn'), '登录后顶栏要有「我的」入口');
  assert(h.get('meBtn').textContent.includes('创作者1234'), '入口显示昵称而不是邮箱');
  assert(!h.get('meBtn').textContent.includes('offline@example.invalid'), '邮箱不能直接摆在顶栏');
  assert(h.get('meBtn').textContent.includes('免费版'), '档位徽标要可见');
  h.click('#meBtn'); await h.flush();
  assert(h.get('meMenu'), '点开要有「我的」菜单');
  assert(h.get('meMenu').textContent.includes('已用 1 / 2 条'), '免费档要展示今日额度');
  assert(h.get('mePricing'), '免费档菜单里要有升级/兑换入口');
  h.evaluate('closeMeMenu()');
  await h.openProject();
  await start(h);
  h.projects[0].renders = [{id: 'job-a', file: 'fixture-job-a.mp4', ts: '2026-01-01 12:00'}];
  h.evaluate('CUR.renders = [{id:"job-a", file:"fixture-job-a.mp4", ts:"2026-01-01 12:00"}]; FLOW.view = "export"; paintFlow()');
  await h.flush();
  assert(h.get('jyBtn').textContent.includes('高级版'), '免费档的剪映按钮要带高级版标记');
  h.click('#jyBtn'); await h.flush();
  assert(h.document.querySelector('.pp-wrap'), '免费档点剪映导出 → 进权益页（不再是弹窗）');
  assert(h.document.querySelector('.pp-wrap').textContent.includes('卡密兑换'), '权益页要交代卡密');
  assert(!h.requests.some(r => r.url.endsWith('/jianying-import')), '没付钱不能真的发导入请求');
});

test('「我的」菜单：权益齐全，顶栏没有独立任务按钮，联系创始人给微信号', async t => {
  const h = await setup(t);
  await h.flush();
  assert.equal(h.get('tasksBtn'), null, '顶栏不再有独立「任务」按钮（收进我的菜单）');
  assert(h.get('tasksBadge'), '任务角标长在「我的」入口上');
  h.click('#meBtn'); await h.flush();
  const menu = h.get('meMenu');
  assert(menu, '点开头像要弹「我的」菜单');
  assert(menu.textContent.includes('offline@example.invalid'), '邮箱在菜单里可见（顶栏不摆）');
  assert(menu.textContent.includes('高级版 · 永久'), '档位徽标要写清买断制');
  assert(menu.textContent.includes('剪映草稿导出'), '高级版权益要列到剪映导出');
  assert(h.get('mePricing') && h.get('mePricing').textContent.includes('我的权益'), '高级版是「我的权益」不是升级');
  assert(h.get('meTasks') && h.get('meLogout'), '任务与退出都在菜单里');
  assert(h.get('meContact'), '要有联系创始人入口');
  h.click('#meTasks'); await h.flush();
  assert(!h.get('meMenu'), '点任务要收起菜单');
  assert(h.get('tasksPanel') && !h.get('tasksPanel').classList.contains('hide'), '要顺手打开任务面板');
  h.evaluate('closeMeMenu(); toggleTasksPanel()');   // 关面板，别和弹窗抢位
  await h.flush();
  h.click('#meBtn'); await h.flush();
  h.click('#meContact'); await h.flush();
  const box = h.document.querySelector('[aria-label="联系创始人"]');
  assert(box, '联系创始人要弹小框');
  assert(box.textContent.includes('getcut-admin'), '微信号来自 /api/pricing 的 wechat_id');
  assert(h.get('ctCopy'), '微信号要能一键复制');
  h.click('#ctCopy'); await h.flush();
  h.click('#ctClose'); await h.flush();
  assert(!h.document.querySelector('[aria-label="联系创始人"]'), '关闭要真关');
});

test('账号设置：头像预设可选，保存资料走 PUT /api/me，改密码走 change-password', async t => {
  const h = await setup(t);
  await h.flush();
  h.click('#meBtn'); await h.flush();
  h.click('#meSettings'); await h.flush();
  const box = h.document.querySelector('[aria-label="账号设置"]');
  assert(box, '账号设置弹窗要打开');
  assert(h.document.querySelectorAll('#acAvs button').length >= 12, '头像预设要摆出来一排');
  assert(h.get('acNick').value === '创作者4231', '昵称预填当前值');
  h.evaluate(`document.getElementById('acAvs').onclick({target: document.querySelector('#acAvs button[data-av="🚀"]')})`);
  assert.equal(h.get('acPrev').textContent, '🚀', '点头像要即时预览');
  h.get('acNick').value = '老王';
  h.get('acNick').oninput({target: h.get('acNick')});
  h.respond('PUT', '/api/me', {ok: true, nickname: '老王', avatar: '🚀'});
  h.click('#acSave'); await h.flush();
  const put = h.requests.find(r => r.url === '/api/me' && r.method === 'PUT');
  assert(put, '保存资料要发 PUT /api/me');
  assert.deepEqual(JSON.parse(put.body), {nickname: '老王', avatar: '🚀'}, '昵称与选中的头像一起提交');
  assert.equal(h.evaluate('ME.nickname'), '老王', '保存后本地 ME 要刷新');
  assert(h.get('meBtn').textContent.includes('老王'), '顶栏立刻用新昵称');
  assert.equal(h.get('meBtn').querySelector('.me-av').textContent, '🚀', '顶栏立刻用新头像');
  h.get('acOld').value = 'old-pass-123';
  h.get('acNew').value = 'new-pass-456';
  h.respond('POST', '/api/auth/change-password', {ok: true});
  h.click('#acPwGo'); await h.flush();
  const pw = h.requests.find(r => r.url === '/api/auth/change-password');
  assert(pw, '改密码要有专门接口');
  assert.deepEqual(JSON.parse(pw.body), {old_password: 'old-pass-123', new_password: 'new-pass-456'});
  assert(h.get('acPwMsg').textContent.includes('密码已更新'), '成功提示要说清下次登录用新密码');
});

test('权益整页：价格/微信/收款码按 /api/pricing 渲染，兑换卡密走 POST，网址落到 #/pricing', async t => {
  const h = await setup(t);
  h.evaluate('openPricing()'); await h.flush();
  const page = h.document.querySelector('.pp-wrap');
  assert(page, '权益页要铺开（不再弹窗）');
  assert.equal(h.evaluate('location.hash'), '#/pricing', '网址要落到 #/pricing，直播间链接可直达');
  assert(page.textContent.includes('¥399') && page.textContent.includes('¥599'), '两档价格要摆出来');
  assert(page.textContent.includes('getcut-admin'), '创始人微信号要展示（直播间销售流程）');
  assert(!h.document.querySelector('.price-qr'), '收款码功能已整体拆除，页面不该出现二维码位');
  h.get('prCode').value = ' gcp-7k2m-9xq4 ';
  h.respond('POST', '/api/license/redeem', {ok: true, message: '激活成功！你现在是高级版', tier: 'premium', tier_label: '高级版'});
  h.click('#prGo'); await h.flush();
  const req = h.requests.find(r => r.url === '/api/license/redeem');
  assert(req, '要点兑换就发请求');
  assert.equal(JSON.parse(req.body).code, 'gcp-7k2m-9xq4', '原文发给服务端，归一化由服务端做');
  assert.equal(h.evaluate('ME.tier'), 'premium', '兑换成功后要用 /api/me 刷新档位');
});

test('音色目录：boot 时拉 /api/voices，百炼没配就回退内置目录照常可点', async t => {
  const h = await setup(t);
  await h.flush();
  assert(h.requests.some(r => r.url === '/api/voices'), 'boot 要刷新音色目录');
  await h.openProject();
  h.click('#voiceSeg [data-v="zh-CN-XiaoxiaoNeural"]');
  assert.equal(h.evaluate('CFG.voice'), 'zh-CN-XiaoxiaoNeural', '回退目录的音色要能选');
});

test('品牌套装：入口收进「我的」菜单，确认页不再打扰；高级版平铺三件事，水印文字存 /api/brand', async t => {
  const h = await setup(t);
  await h.openProject();
  assert.equal(h.get('brandBtn'), null, '确认页不再有品牌套件入口（用户只管点点点）');
  assert.equal(h.get('epBadge'), null, '期数角标输入已下线');
  // 免费档：菜单里带锁，点了进权益页
  await h.evaluate('ME = {...ME, tier: "free", tier_label: "免费版"}');
  h.click('#meBtn'); await h.flush();
  assert.match(h.get('meBrand').textContent, /高级版/, '免费档菜单里品牌套装要带锁');
  h.click('#meBrand'); await h.flush();
  assert(h.document.querySelector('.pp-wrap'), '免费档点品牌套装 → 进权益页');
  // 高级档：菜单点开品牌套装，Logo / 我的声音 / 文字水印 平铺
  await h.evaluate('ME = {...ME, tier: "premium", tier_label: "高级版"}');
  h.respond('GET', '/api/brand', {brand: {watermark_text: '@老王看财经'}, premium: true, has_logo: true});
  h.respond('GET', '/api/voice-clone', {premium: true, dashscope: true, clone: {voice_id: 'v1', created: '2026-09-19 10:00'}, has_voice: true});
  h.respond('PUT', '/api/brand', {ok: true, brand: {}});
  h.click('#meBtn'); await h.flush();
  assert(h.get('meBrand').textContent.includes('Logo'), '高级版菜单里要写清品牌套装里有什么');
  h.click('#meBrand'); await h.flush();
  const box = h.document.querySelector('[aria-label="品牌套装"]');
  assert(box, '高级版要点开品牌套装弹窗');
  assert(h.get('bkLogo'), 'Logo 上传入口要在');
  assert(box.textContent.includes('已克隆'), '已克隆状态要显示');
  assert.equal(h.get('bkWm').value, '@老王看财经', '水印文字要回填');
  h.get('bkWm').value = '@阿伟说财经';
  h.get('bkWm').onchange();
  await h.flush();
  const put = h.requests.find(r => r.url === '/api/brand' && r.method === 'PUT');
  assert(put, '水印文字要走 PUT /api/brand');
  assert.deepEqual(JSON.parse(put.body), {watermark_text: '@阿伟说财经'}, '改完即存，不带旧字段');
});

test('出片请求不带 brand 字段——品牌由服务端按账号自动注入，前端伪造无效', async t => {
  const h = await setup(t);
  await h.openProject();
  await start(h);
  const body = JSON.parse(builds(h)[0].body);
  assert(!('brand' in body), '前端不传 brand');
});

test('栏目角标已下线：确认页没有期数输入，出片请求也不带 series', async t => {
  const h = await setup(t);
  await h.openProject();
  assert.equal(h.get('epBadge'), null, '期数角标输入已下线');
  await start(h);
  const body = JSON.parse(builds(h)[0].body);
  assert(!('series' in body), '出片请求不再带 series');
});
