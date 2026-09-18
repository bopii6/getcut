'use strict';

// Offline only: no server, renderer, browser or real storage is used.
// Use an installed LinkeDOM via NODE_PATH, or VIDEOGEN_TEST_DOM=/absolute/path/to/linkedom.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
let dom;
try {
  dom = require(process.env.VIDEOGEN_TEST_DOM || 'linkedom');
} catch (error) {
  throw new Error('Offline frontend tests require LinkeDOM (tested with 0.18.12). ' +
    'Set NODE_PATH to an existing node_modules, or VIDEOGEN_TEST_DOM to its linkedom directory.', {cause: error});
}

const HTML_PATH = path.resolve(__dirname, '../server_static/index.html');
const html = fs.readFileSync(HTML_PATH, 'utf8');
const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)];
assert(scripts.length && scripts.every(s => !/\bsrc\s*=/.test(s[1])), 'Harness expects production inline scripts');
const clone = value => JSON.parse(JSON.stringify(value));
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}
function bundle(name) {
  return {name, title: name, script: '离线回归测试口播文案。', estSeconds: 60,
    hookLines: [{text: '离线测试', highlight: '测试'}], sources: [], pronunciations: {}, notes: '',
    assets: [{id: 'asset1', kind: 'image', file: 'images/fixture.jpg', summary: '本地模拟素材'}],
    mediaBase: '/media/' + name};
}
function project(id = 'aa', name = 'bundle-a') {
  return {project_id: id, title: 'Project ' + id, bundle: name, renders: [], renders_count: 0, assets_count: 1};
}
const queued = (pid = 'aa') => ({project_id: pid, stage: 'queued', stage8: 1, progress: 3,
  detail: '排队中 · 前面还有 1 个任务', queued_pos: 1, error: null, video: null, elapsed: 0, stills: []});

async function createHarness({storage = {}} = {}) {
  const {document, window: domWindow} = dom.parseHTML(html);
  // LinkeDOM deliberately omits these browser behaviors. Only DOM mechanics are shimmed;
  // application functions and fetch/api are never replaced by test implementations.
  const selectValue = Object.getOwnPropertyDescriptor(domWindow.HTMLSelectElement.prototype, 'value');
  if (!selectValue.set) Object.defineProperty(domWindow.HTMLSelectElement.prototype, 'value', {
    configurable: true, get: selectValue.get,
    set(value) { for (const option of this.options) option.selected = option.value === String(value); }
  });
  for (const name of ['play', 'pause', 'load', 'scrollIntoView', 'select']) {
    if (!domWindow.HTMLElement.prototype[name]) Object.defineProperty(domWindow.HTMLElement.prototype, name, {
      configurable: true, value: name === 'play' ? () => Promise.resolve() : () => {}
    });
  }
  // Native dialog shims: LinkeDOM omits HTMLDialogElement; patch the live element prototype.
  const DialogProto = domWindow.HTMLDialogElement
    ? domWindow.HTMLDialogElement.prototype
    : Object.getPrototypeOf(document.createElement('dialog'));
  DialogProto.showModal = function () { this.setAttribute('open', ''); };
  DialogProto.close = function () {
    this.removeAttribute('open');
    this.dispatchEvent(new domWindow.Event('close'));
  };
  const values = new Map(Object.entries(storage));
  const localStorage = {getItem: k => values.has(k) ? values.get(k) : null,
    setItem: (k, v) => values.set(k, String(v)), removeItem: k => values.delete(k), clear: () => values.clear()};
  const requests = [], unexpected = [], errors = [], timers = new Map(), routes = new Map();
  let timerId = 0;
  const schedule = (fn, ms, repeat, args) => {
    const id = ++timerId; timers.set(id, {fn, ms, repeat, args}); return id;
  };
  const projects = [project(), project('bb', 'bundle-b')];
  const jobStates = new Map([['job-a', queued()], ['job-b', queued('bb')]]);
  function respond(method, url, handler) { routes.set(method + ' ' + url, handler); }
  respond('GET', '/api/me', {email: 'offline@example.invalid'});
  respond('GET', '/api/auth/status', {locked: false, smtp: false, dev_email: false, token_auth: false});
  respond('GET', '/api/templates', {default: 'editorial', templates: ['editorial', 'news', 'data', 'poster', 'bleed', 'zhigu'].map(id => ({id, name: id}))});
  respond('GET', '/api/projects', () => projects);
  respond('GET', '/api/jobs', {concurrency: 1, active: [], recent: []});
  respond('GET', '/api/bundles', projects.map(p => ({name: p.bundle, assets: 1, updated: '2026-01-01'})));
  respond('GET', '/api/bundle/bundle-a', bundle('bundle-a'));
  respond('GET', '/api/bundle/bundle-b', bundle('bundle-b'));
  respond('GET', '/api/music', [{file: 'assets/music/test.mp3', name: 'Fixture', mood: 'neutral'}]);
  respond('GET', '/api/job/job-a', () => jobStates.get('job-a'));
  respond('GET', '/api/job/job-b', () => jobStates.get('job-b'));
  const fetch = async (url, options = {}) => {
    const req = {url: String(url), method: (options.method || 'GET').toUpperCase(), ...options};
    requests.push(req);
    const key = req.method + ' ' + req.url;
    if (!routes.has(key)) {
      unexpected.push(key);
      throw new Error('Unmocked request blocked: ' + key);
    }
    const handler = routes.get(key);
    const value = await (typeof handler === 'function' ? handler(req) : handler);
    const status = value && value.__httpStatus || 200;
    const body = value && value.__httpStatus ? value.body : value;
    return {ok: status >= 200 && status < 300, status, json: async () => clone(body)};
  };
  // No native fetch, XMLHttpRequest, WebSocket, process, require, or filesystem in VM globals.
  // This is an offline test environment, not a hostile-code security sandbox.
  const sandbox = {document, localStorage, fetch, URL, URLSearchParams,
    location: {hash: '#/', href: 'https://offline.invalid/#/', origin: 'https://offline.invalid'},
    navigator: {clipboard: {writeText: async () => {}}},
    console: {log() {}, warn() {}, error: (...args) => errors.push(args.join(' '))},
    setTimeout: (fn, ms, ...args) => schedule(fn, ms, false, args),
    setInterval: (fn, ms, ...args) => schedule(fn, ms, true, args),
    clearTimeout: id => timers.delete(id), clearInterval: id => timers.delete(id),
    addEventListener() {}, removeEventListener() {}, scrollTo() {},
    Audio: function () { this.play = async () => {}; this.pause = () => {}; },
    open: () => { throw new Error('Opening external windows is forbidden in offline tests'); },
    FormData: class { constructor() { this.entries = []; } append(...args) { this.entries.push(args); } }
  };
  sandbox.window = sandbox;
  const context = vm.createContext(sandbox);
  const evaluate = code => vm.runInContext(code, context, {filename: 'frontend-test-driver', timeout: 3000});
  for (const [index, script] of scripts.entries()) {
    vm.runInContext(script[2], context, {filename: HTML_PATH + ':inline-' + index, timeout: 3000});
  }
  const flush = async () => { for (let n = 0; n < 30; n++) await Promise.resolve(); };
  await flush();
  return {
    document, localStorage, requests, unexpected, errors, timers, projects, jobStates, respond, evaluate, flush,
    get: id => document.getElementById(id),
    async openProject(p = projects[0]) {
      const result = evaluate(`CUR = ${JSON.stringify(clone(p))}; setHash('#/project/' + CUR.project_id); renderProject()`);
      await result; await flush();
    },
    async tick(ms = 1500) {
      for (const [id, timer] of [...timers]) {
        if (timer.ms !== ms || !timers.has(id)) continue;
        if (!timer.repeat) timers.delete(id);
        await timer.fn(...timer.args);
      }
      await flush();
    },
    click(selector) {
      const element = document.querySelector(selector);
      assert(element, 'Missing click target ' + selector);
      assert(!element.disabled && !element.hasAttribute('disabled'), 'Disabled click target ' + selector);
      // LinkeDOM does not dispatch assigned onclick properties like a browser.
      assert.equal(typeof element.onclick, 'function', 'No onclick handler for ' + selector);
      return element.onclick({target: element, currentTarget: element, preventDefault() {}, stopPropagation() {}});
    },
    clean() {
      timers.clear();
      assert.deepEqual(unexpected, [], 'Every request must be explicitly mocked');
      assert.deepEqual(errors, [], 'No application console errors');
    }
  };
}
module.exports = {createHarness, deferred, bundle, project, queued};
