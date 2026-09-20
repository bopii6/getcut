import React from 'react';
import {C, btnSm, btnSmLine, inp, api, Sheet, Msg} from './ui';

interface BrandSt {
  brand: {watermark_text?: string}; premium: boolean; has_logo: boolean;
}
interface CloneSt { premium: boolean; dashscope: boolean; has_voice: boolean;
                   clone?: {created?: string} | null }

const sec: React.CSSProperties = {borderTop: `1px solid ${C.line}`, paddingTop: 18, marginTop: 18};
const secTitle: React.CSSProperties = {fontSize: 14.5, fontWeight: 800, marginBottom: 3};
const secSub: React.CSSProperties = {fontSize: 12.5, color: C.soft, marginBottom: 12};

/**
 * 品牌套装（高级版）：Logo / 我的声音 / 文字水印，改完即存。
 * 出片时服务端按账号自动带上（/api/build 里 _brand_for(会话邮箱)），本页不参与传参。
 */
export const BrandSheet: React.FC<{
  onClose: () => void; toast: (m: string) => void; onBrandChanged: () => void;
}> = ({onClose, toast, onBrandChanged}) => {
  const [st, setSt] = React.useState<BrandSt | null>(null);
  const [cl, setCl] = React.useState<CloneSt | null>(null);
  const [wm, setWm] = React.useState('');
  const [wmMsg, setWmMsg] = React.useState<{t: string; k: 'err' | 'ok'}>({t: '', k: 'err'});
  const [logoMsg, setLogoMsg] = React.useState('');
  const [recState, setRecState] = React.useState<'idle' | 'rec' | 'done'>('idle');
  const [recSec, setRecSec] = React.useState(0);
  const [blobUrl, setBlobUrl] = React.useState('');
  const [consent, setConsent] = React.useState(false);
  const [recMsg, setRecMsg] = React.useState<{t: string; k: 'err' | 'ok' | 'info'}>({t: '', k: 'err'});
  const rec = React.useRef<{mr: MediaRecorder | null; chunks: Blob[]; timer: number; stream: MediaStream | null}>(
    {mr: null, chunks: [], timer: 0, stream: null});

  const load = React.useCallback(() => {
    api('/api/brand').then((d) => {
      const b = d as unknown as BrandSt;
      setSt(b);
      setWm(String(b.brand?.watermark_text || ''));
    }).catch((e) => toast(String((e as Error).message)));
    api('/api/voice-clone').then((d) => setCl(d as unknown as CloneSt)).catch(() => {});
  }, [toast]);
  React.useEffect(() => { load(); }, [load]);

  const stopTracks = () => {
    rec.current.stream?.getTracks().forEach((t) => t.stop());
    rec.current.stream = null;
  };
  React.useEffect(() => () => {
    window.clearInterval(rec.current.timer);
    stopTracks();
  }, []);

  const uploadLogo = async (file?: File) => {
    if (!file) return;
    setLogoMsg('上传中…');
    try {
      const fd = new FormData();
      fd.append('file', file);
      await api('/api/brand/logo', {method: 'POST', body: fd});
      setLogoMsg('已上传，之后的出片自动带上');
      toast('Logo 已上传');
      load();
      onBrandChanged();
    } catch (e) {
      setLogoMsg(String((e as Error).message));
    }
  };
  const dropLogo = async () => {
    try {
      await api('/api/brand/logo', {method: 'DELETE'});
      load();
      onBrandChanged();
    } catch (e) {
      setLogoMsg(String((e as Error).message));
    }
  };
  const saveWm = async () => {
    setWmMsg({t: '', k: 'err'});
    try {
      await api('/api/brand', {method: 'PUT', headers: {'content-type': 'application/json'},
        body: JSON.stringify({watermark_text: wm.trim()})});
      setWmMsg({t: wm.trim() ? '已保存，出片右上角就是它' : '已保存，水印显示 Powered by GetCut', k: 'ok'});
      onBrandChanged();

    } catch (e) {
      setWmMsg({t: String((e as Error).message), k: 'err'});
    }
  };

  const startRec = async () => {
    setRecMsg({t: '', k: 'err'});
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      setRecMsg({t: '这个浏览器不支持录音，换 Chrome/Edge 试试', k: 'err'});
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({audio: true});
      rec.current.stream = stream;
      rec.current.chunks = [];
      const mr = new MediaRecorder(stream);
      rec.current.mr = mr;
      mr.ondataavailable = (e) => rec.current.chunks.push(e.data);
      mr.onstop = () => {
        stopTracks();
        window.clearInterval(rec.current.timer);
        const blob = new Blob(rec.current.chunks, {type: mr.mimeType || 'audio/webm'});
        setBlobUrl(URL.createObjectURL(blob));
        setRecState('done');
        setRecMsg({t: '录好了，先听一听，满意就点「用这段克隆我的声音」', k: 'info'});
      };
      mr.start();
      setRecState('rec');
      setRecSec(0);
      setRecMsg({t: '在安静的地方，用平时说话的语气读一段稿子，30 秒左右', k: 'ok'});
      const t0 = Date.now();
      rec.current.timer = window.setInterval(() => {
        const s = Math.floor((Date.now() - t0) / 1000);
        setRecSec(s);
        if (s >= 45) rec.current.mr?.stop();   // 45 秒封顶，30 秒左右效果最好
      }, 250);
    } catch (_) {
      setRecMsg({t: '麦克风没权限，到浏览器地址栏允许一下', k: 'err'});
    }
  };
  const cloneWith = async () => {
    if (!blobUrl) return;
    setRecMsg({t: '上传并克隆中，约十几秒…', k: 'ok'});
    try {
      const blob = await (await fetch(blobUrl)).blob();
      const fd = new FormData();
      fd.append('file', blob, 'voice.webm');
      await api('/api/voice-clone', {method: 'POST', body: fd});
      setRecMsg({t: '克隆成功！音色列表里选「我的声音」就能用你的声音配音', k: 'ok'});
      toast('我的声音已就绪');
      load();
      onBrandChanged();
    } catch (e) {
      setRecMsg({t: String((e as Error).message), k: 'err'});
    }
  };
  const dropClone = async () => {
    setRecMsg({t: '', k: 'err'});
    try {
      await api('/api/voice-clone', {method: 'DELETE'});
      toast('我的声音已清除');
      load();
      onBrandChanged();
    } catch (e) {
      setRecMsg({t: String((e as Error).message), k: 'err'});
    }
  };

  const mm = `${Math.floor(recSec / 60)}:${String(recSec % 60).padStart(2, '0')}`;
  const premium = st?.premium !== false;

  return (
    <Sheet title="品牌套装" sub="跟着账号走，之后的每条片子自动带上。" width={520} onClose={onClose}>
      {!st ? <div style={{fontSize: 13.5, color: C.soft}}>加载中…</div> : (
        <>
          {/* Logo */}
          <div style={{display: 'flex', gap: 16, alignItems: 'center'}}>
            <div style={{
              width: 76, height: 76, flexShrink: 0, borderRadius: 10, overflow: 'hidden',
              border: `1px dashed ${C.line}`, background: '#fff', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
            }}>
              {st.has_logo
                ? <img src={`/api/brand/logo?t=${Date.now()}`} alt="Logo"
                       style={{maxWidth: 68, maxHeight: 68, objectFit: 'contain'}} />
                : <span style={{fontSize: 12.5, color: C.soft}}>还没传</span>}
            </div>
            <div style={{minWidth: 0}}>
              <div style={secTitle}>Logo</div>
              <div style={secSub}>开场就让人认出你 · PNG 透明底最佳</div>
              <div style={{display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap'}}>
                <label style={{...btnSmLine, cursor: 'pointer', display: 'inline-block'}}>
                  {st.has_logo ? '换一张' : '上传 Logo'}
                  <input type="file" accept="image/png,image/jpeg,image/webp" style={{display: 'none'}}
                         onChange={(e) => void uploadLogo(e.target.files?.[0])} />
                </label>
                {st.has_logo ? (
                  <button style={btnSmLine} onClick={() => void dropLogo()}>移除</button>
                ) : null}
              </div>
              {logoMsg ? <div style={{fontSize: 12.5, color: C.soft, marginTop: 6}}>{logoMsg}</div> : null}
            </div>
          </div>

          {/* 我的声音 */}
          <div style={sec}>
            <div style={secTitle}>我的声音</div>
            <div style={secSub}>录 30 秒，之后配音就用你的声音</div>
            {cl?.has_voice ? (
              <div style={{fontSize: 13, color: C.ok, marginBottom: 10}}>
                已克隆{cl.clone?.created ? ` · ${cl.clone.created}` : ''}，重录可覆盖
              </div>
            ) : null}
            {cl && !cl.dashscope ? (
              <div style={{fontSize: 13, color: C.soft, marginBottom: 10, lineHeight: 1.7}}>
                配音服务尚未配置（等站长开通百炼），现在录音还不能克隆。
              </div>
            ) : null}
            <div style={{display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap'}}>
              <button style={recState === 'rec' ? {...btnSm, background: C.err} : btnSm}
                      onClick={() => (recState === 'rec' ? rec.current.mr?.stop() : void startRec())}>
                {recState === 'rec' ? `■ 停止 ${mm}` : recState === 'done' ? '● 重新录' : '● 开始录音'}
              </button>
              {blobUrl ? <audio controls src={blobUrl} style={{height: 30}} /> : null}
              <button style={{...btnSmLine, opacity: consent && blobUrl && recState === 'done' ? 1 : 0.45}}
                      disabled={!(consent && blobUrl && recState === 'done')}
                      onClick={() => void cloneWith()}>用这段克隆我的声音</button>
              {cl?.has_voice ? (
                <button style={{...btnSmLine, color: C.err, borderColor: C.err}}
                        onClick={() => void dropClone()}>清除我的声音</button>
              ) : null}
            </div>
            <label style={{display: 'flex', gap: 7, alignItems: 'flex-start', fontSize: 12.5,
                           color: C.soft, marginTop: 12, lineHeight: 1.7, cursor: 'pointer'}}>
              <input type="checkbox" checked={consent} style={{marginTop: 2}}
                     onChange={(e) => setConsent(e.target.checked)} />
              <span>我确认录制的是<b>我本人</b>的声音，并同意 GetCut 用它合成我账号下的视频配音。
                成片按规范标注 AI 配音。</span>
            </label>
            <Msg {...recMsg} />
          </div>

          {/* 文字水印 */}
          <div style={sec}>
            <div style={secTitle}>文字水印</div>
            <div style={secSub}>出在每条片子右上角，如「@阿伟说财经」</div>
            <input style={inp} maxLength={16} value={wm} placeholder="留空 = 显示 Powered by GetCut"
                   onChange={(e) => setWm(e.target.value)} onBlur={() => void saveWm()} />
            <Msg {...wmMsg} />
          </div>

          {!premium ? (
            <div style={{...sec, fontSize: 13, color: C.err}}>
              品牌套装是高级版功能——升级后这里改的东西才真正上片。
            </div>
          ) : null}
        </>
      )}
    </Sheet>
  );
};
