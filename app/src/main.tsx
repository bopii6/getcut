import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import Workbench from './Workbench.tsx';
import MobileApp from './MobileApp.tsx';

/** 手机 / 竖屏走向导版，桌面走编辑器版 */
function Root() {
  const [isMobile, setIsMobile] = useState(() => window.matchMedia('(max-width: 900px)').matches);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)');
    const onChange = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  return isMobile ? <MobileApp /> : <Workbench />;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Root />
  </StrictMode>,
);

