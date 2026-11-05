// 服务端地址：只写到域名/IP，不带路径。三档，按你在哪跑选：
//   'http://127.0.0.1:8902'      → 本机后端，只在微信开发者工具的模拟器里有效
//   'http://115.190.113.128'     → 火山引擎那台（同一 WiFi 或模拟器可用，需勾「不校验合法域名」）
//   'https://你的域名'            → 真机预览、体验版、正式版唯一合法的形态，必须备案 + HTTPS
const API_BASE = 'http://127.0.0.1:8902';

// 接口挂载前缀。服务器上 Web 端的旧后端占了 /api，所以出片服务挂在 /v1。
const API_PREFIX = '/v1';

App({
  globalData: {
    apiBase: API_BASE,
    apiPrefix: API_PREFIX,
  },

  onLaunch() {
    const info = wx.getAccountInfoSync ? wx.getAccountInfoSync() : null;
    const env = info && info.miniProgram ? info.miniProgram.envVersion : 'unknown';
    // 开发版/体验版才允许 http，正式版必须 https——微信不给例外
    if (env !== 'release' && /^http:\/\//.test(this.globalData.apiBase)) {
      console.warn('[getcut] 当前是 http，仅开发/体验版可用');
    }
  },
});
