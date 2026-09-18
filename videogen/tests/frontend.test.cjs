'use strict';

// Run: VIDEOGEN_TEST_DOM=<path-to-linkedom> node --test videogen/tests/frontend.test.cjs
// Production contract (server.py + server_static/index.html flow views):
//   /api/build keys: project_id, bundle, voice, rate(String), bgm, sfx(bool), sfxMode,
//     subtitles, sources, format, disclaimer, useLlm -> {job}
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
async function configure(h, {format, voice, rate, sfx, subtitles, sources, bgm, disclaimer}) {
  const wanted = [format, voice, rate, sfx, subtitles, sources, bgm, disclaimer].some(v => v !== undefined);
  if (!wanted) return;
  await h.flush(); // music select 的 onchange 在 /api/music 解析后才挂上
  if (format !== undefined) h.click('#fmt [data-v="' + format + '"]');
  if (voice !== undefined) h.click('#voiceSeg [data-v="' + voice + '"]');
  if (rate !== undefined) h.click('#rateSeg [data-r="' + rate + '"]');
  if (sfx !== undefined) h.click('#sfxSeg [data-v="' + sfx + '"]');
  if (subtitles !== undefined) h.click('.swt[data-k="subtitles"]');
  if (sources !== undefined) h.click('.swt[data-k="sources"]');
  if (bgm !== undefined) { h.get('bgm').value = bgm; h.get('bgm').onchange(); }
  if (disclaimer !== undefined) {
    const el = h.get('disclaimer');
    el.value = disclaimer;
    el.oninput({target: el});
  }
}

test('production boot loads templates and projects entirely through mocked fetch', async t => {
  const h = await setup(t);
  assert(h.get('topNew'), '顶栏必须常驻「新建项目」入口');
  assert.equal(h.evaluate('TPLS.length'), 7);
  assert(h.requests.some(r => r.url === '/api/templates'));
  assert(h.requests.some(r => r.url === '/api/projects'));
});

test('actual configuration controls serialize the exact production build payload', async t => {
  const h = await setup(t);
  await h.openProject();
  await configure(h, {format: 'finance', voice: 'zh-CN-XiaoxiaoNeural', rate: 125,
    sfx: 'off', subtitles: false, sources: false, bgm: 'assets/music/test.mp3',
    disclaimer: '  离线测试免责声明  '});
  h.respond('POST', '/api/build', {job: 'job-a'});
  await h.click('#go');
  await h.flush();
  assert.equal(builds(h).length, 1);
  assert.deepEqual(JSON.parse(builds(h)[0].body), {
    project_id: 'aa', bundle: 'bundle-a', voice: 'zh-CN-XiaoxiaoNeural', rate: '125',
    bgm: 'assets/music/test.mp3', sfx: false, sfxMode: 'off', subtitles: false,
    sources: false, format: 'finance', disclaimer: '离线测试免责声明', useLlm: true
  });
  assert.equal(builds(h)[0].headers['Content-Type'], 'application/json');
  assert.equal(h.localStorage.getItem('vg.job.aa'), 'job-a');
});

test('all sound effect modes preserve production sfx boolean semantics', async t => {
  for (const mode of ['off', 'hook', 'accent', 'full']) {
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
  const h = await setup(t, {storage: {'vg.cfg': JSON.stringify({format: 'retro', voice: 'zh-CN-YunjianNeural', rate: 90})}});
  await h.openProject();
  assert(h.document.querySelector('#fmt [data-v="retro"]').classList.contains('on'));
  assert(h.document.querySelector('#voiceSeg [data-v="zh-CN-YunjianNeural"]').classList.contains('on'));
  assert(h.document.querySelector('#rateSeg [data-r="90"]').classList.contains('on'));
});

test('malformed saved configuration safely falls back to defaults', async t => {
  const h = await setup(t, {storage: {'vg.cfg': '{bad-json'}});
  assert.equal(h.evaluate('CFG.format'), 'editorial');
  assert.equal(h.evaluate('CFG.rate'), 100);
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
  assert.match(h.get('jyBtn').getAttribute('href'), /\/api\/projects\/aa\/renders\/job-a\/jianying-draft/);
  assert.equal(h.document.querySelectorAll('#hist [data-render="job-a"]').length, 1);
  assert.equal(h.requests.filter(r => /jianying-draft/.test(r.url)).length, 0, 'Downloads must not run implicitly');
});

test('generation view keeps the decision before the render and shows no per-stage detail', async t => {
  const h = await setup(t);
  await h.openProject();
  assert(h.get('fmt'), '确认页要能直接选画面模板');
  assert(h.get('voiceSeg'), '确认页要能直接选配音');
  assert(h.get('bgm'), '确认页要能直接选背景音乐');
  assert(h.get('sfxSeg'), '确认页要能直接选音效');
  assert.equal(h.document.querySelectorAll('.vg-choices .tpl').length, 7, '模板要摆在页面上，不是弹窗里');
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
  await h.click('#fmt [data-v="retro"]');
  assert(grid.classList.contains('hide'), '选完要自动收起');
  assert.equal(h.evaluate('CFG.format'), 'retro');
  assert.match(h.get('tplNow').textContent, /retro/, '那一格要换成新选的');
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
