import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import Workbench from './Studio.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Workbench />
  </StrictMode>,
);


