// 服务端接口的薄封装。小程序没有 fetch，只有 wx.request，回调式，包一层 Promise。

function base() {
  const app = getApp();
  const url = (app && app.globalData && app.globalData.apiBase) || '';
  return url.replace(/\/+$/, '');
}

// 服务端把接口挂在哪个前缀下，由 app.js 一处决定。
// 这台服务器上 Web 端的旧后端占了 /api，新服务挂在 /v1。
function prefix() {
  const app = getApp();
  const p = (app && app.globalData && app.globalData.apiPrefix) || '';
  return p.replace(/\/+$/, '');
}

function request(path, { method = 'GET', data } = {}) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: base() + prefix() + path,
      method,
      data,
      header: { 'content-type': 'application/json' },
      timeout: 120000,
      success(res) {
        if (res.statusCode >= 200 && res.statusCode < 300) {
          resolve(res.data);
          return;
        }
        const msg = (res.data && res.data.error) || `服务返回 ${res.statusCode}`;
        reject(new Error(msg));
      },
      fail(err) {
        // 真机上最常见的是域名没配白名单，报错长得像网络问题，这里说人话
        reject(new Error(`连不上出片服务（${err.errMsg || '未知原因'}）`));
      },
    });
  });
}

/** 只拆稿，不渲染，秒回。给用户先看分镜用。 */
function plan(text) {
  return request('/plan', { method: 'POST', data: { text } });
}

/** 建出片任务，立刻拿到 id，不等渲染。 */
function createJob(payload) {
  return request('/job', { method: 'POST', data: payload });
}

/** 查进度。 */
function getJob(id) {
  return request(`/job/${id}`);
}

/** 拼成片地址（video 组件直接吃这个 URL）。
 *  服务端返回的 videoPath 已经带了前缀（/v1/video/xxx），所以这里不加 prefix，只拼域名。 */
function videoUrl(path) {
  if (!path) return '';
  return base() + path;
}

module.exports = { request, plan, createJob, getJob, videoUrl };
