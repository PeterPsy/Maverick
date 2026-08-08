import { useEffect, useState } from 'react';
import { callBackend, type BackendStatus } from './api';

export function App() {
  const [status, setStatus] = useState<BackendStatus>({});

  useEffect(() => {
    callBackend({ action: 'status' }).then(setStatus).catch((error: Error) => setStatus({ status: error.message }));
  }, []);

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Maverick workspace app</p>
        <h1>Video Studio</h1>
        <p>This React/Vite app is mounted by Maverick and calls its own backend surface.</p>
      </section>
      <section className="status-panel">
        <h2>Status</h2>
        <pre>{JSON.stringify(status, null, 2)}</pre>
      </section>
    </main>
  );
}
