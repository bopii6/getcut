// 服务端地址放这里改一处。上线前记得：
//   1. 小程序后台 → 开发管理 → 开发设置 → 服务器域名，把域名加到 request 和 downloadFile 里
//   2. 必须是 https，且域名已备案
//   3. 开发阶段可以勾「不校验合法域名」，真机预览会失效，别指望它
const API_BASE = 'https://getcut.example.com';

App({
  globalData: {
    apiBase: API_BASE,
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
