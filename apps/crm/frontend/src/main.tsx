import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';
import './records.css';
import './pipeline.css';
import './record-composer.css';
import './import.css';
import './detail.css';
import './detail-linked.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
