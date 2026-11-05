const api = require('../../utils/api.js');

const POLL_MS = 2000;

Page({
  data: {
    id: '',
    status: 'queued',
    stage: '排队中',
    percent: 0,
    queueAhead: 0,
    videoUrl: '',
    error: '',
    saving: false,
    saved: false,
    tip: '',
  },

  onLoad(options) {
    const id = options.id || '';
    if (!id) {
      this.setData({ status: 'failed', error: '没拿到任务号，回上一步重来' });
      return;
    }
    this.setData({ id });
    this.poll();
  },

  onUnload() {
    this.stopPoll();
  },

  onHide() {
    // 切后台就别轮询了，微信会掐请求，回来再续上
    this.stopPoll();
  },

  onShow() {
    if (this.data.id && this.data.status !== 'done' && this.data.status !== 'failed') this.poll();
  },

  stopPoll() {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  },

  async poll() {
    this.stopPoll();
    try {
      const job = await api.getJob(this.data.id);

      if (job.status === 'done') {
        this.setData({
          status: 'done',
          stage: '完成',
          percent: 100,
          videoUrl: api.videoUrl(job.videoPath),
          queueAhead: 0,
          error: '',
        });
        return;
      }

      if (job.status === 'failed') {
        this.setData({ status: 'failed', stage: '失败', error: job.error || '渲染失败' });
        return;
      }

      this.setData({
        status: job.status,
        stage: job.stage || '处理中',
        percent: job.percent || 0,
        queueAhead: job.queueAhead || 0,
      });
      this.timer = setTimeout(() => this.poll(), POLL_MS);
    } catch (err) {
      // 网络抖一下不该判定失败，退避重试几次
      this.retries = (this.retries || 0) + 1;
      if (this.retries > 5) {
        this.setData({ status: 'failed', error: err.message || '查询进度失败' });
        return;
      }
      this.timer = setTimeout(() => this.poll(), POLL_MS * this.retries);
    }
  },

  onRetry() {
    this.retries = 0;
    this.setData({ status: 'queued', error: '', percent: 0, stage: '重新查询' });
    this.poll();
  },

  /** 存相册：先下载到临时文件，再申请相册权限。被拒过要引导去设置页，否则永远存不进去。 */
  async onSave() {
    if (this.data.saving || !this.data.videoUrl) return;
    this.setData({ saving: true, tip: '' });

    try {
      const filePath = await this.download();
      await this.saveToAlbum(filePath);
      this.setData({ saved: true, tip: '已存到相册' });
    } catch (err) {
      this.setData({ tip: err.message || '保存失败' });
    } finally {
      this.setData({ saving: false });
    }
  },

  download() {
    return new Promise((resolve, reject) => {
      wx.downloadFile({
        url: this.data.videoUrl,
        timeout: 180000,
        success(res) {
          if (res.statusCode === 200 && res.tempFilePath) resolve(res.tempFilePath);
          else reject(new Error(`下载失败（${res.statusCode}）`));
        },
        fail(err) {
          reject(new Error(`下载失败：${err.errMsg || '网络问题'}`));
        },
      });
    });
  },

  saveToAlbum(filePath) {
    return new Promise((resolve, reject) => {
      wx.saveVideoToPhotosAlbum({
        filePath,
        success: resolve,
        fail(err) {
          const msg = err.errMsg || '';
          if (msg.indexOf('auth deny') >= 0 || msg.indexOf('authorize') >= 0) {
            wx.showModal({
              title: '需要相册权限',
              content: '保存到相册要开一下权限，去设置里打开再回来点一次',
              confirmText: '去设置',
              success(r) {
                if (r.confirm) wx.openSetting({});
              },
            });
            reject(new Error('没有相册权限'));
            return;
          }
          reject(new Error(`保存失败：${msg}`));
        },
      });
    });
  },

  onPreview() {
    if (!this.data.videoUrl) return;
    wx.previewMedia({
      sources: [{ url: this.data.videoUrl, type: 'video' }],
    });
  },

  onBack() {
    wx.navigateBack({
      fail() {
        wx.reLaunch({ url: '/pages/index/index' });
      },
    });
  },
});
