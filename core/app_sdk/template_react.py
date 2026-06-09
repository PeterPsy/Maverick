"""React/Vite template files for SDK-generated apps."""

from __future__ import annotations

from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.template_common import title_from_slug


def react_vite_files(request: AppSdkCreateRequest) -> dict[str, str]:
    """Return React/Vite source plus a committed dist smoke build."""
    title = request.name or title_from_slug(request.app_id)
    app_id = request.app_id
    files = {
        ".npmrc": "engine-strict=true\n",
        "package.json": f'''{{
  "name": "{app_id}",
  "version": "{request.version}",
  "private": true,
  "type": "module",
  "engines": {{
    "node": ">=24.11.0 <25"
  }},
  "scripts": {{
    "prebuild": "node scripts/check-node-runtime.mjs",
    "build": "tsc --noEmit && vite build",
    "predev": "node scripts/check-node-runtime.mjs",
    "dev": "vite --host 0.0.0.0"
  }},
  "dependencies": {{
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  }},
  "devDependencies": {{
    "@types/react": "^19.0.0",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^5.0.0",
    "typescript": "^5.0.0",
    "vite": "^7.0.0"
  }}
}}
''',
        "scripts/check-node-runtime.mjs": _node_runtime_check_script(),
        "tsconfig.json": """{
  "compilerOptions": {
    "target": "ES2022",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["frontend/src"]
}
""",
        "vite.config.ts": _vite_config(app_id, include_widget=request.template_id == "widget"),
        "frontend/index.html": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{title}</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
""",
        "frontend/src/api.ts": f"""export type BackendStatus = {{
  app_id?: string;
  workspace_id?: string | null;
  status?: string;
  [key: string]: unknown;
}};

export async function callBackend<T = BackendStatus>(body: Record<string, unknown>): Promise<T> {{
  const response = await fetch('/api/apps/{app_id}/backend', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body)
  }});
  if (!response.ok) {{
    throw new Error(`Backend request failed with ${{response.status}}`);
  }}
  return response.json() as Promise<T>;
}}
""",
        "frontend/src/App.tsx": f"""import {{ useEffect, useState }} from 'react';
import {{ callBackend, type BackendStatus }} from './api';

export function App() {{
  const [status, setStatus] = useState<BackendStatus>({{}});

  useEffect(() => {{
    callBackend({{ action: 'status' }}).then(setStatus).catch((error: Error) => setStatus({{ status: error.message }}));
  }}, []);

  return (
    <main className="app-shell">
      <section className="hero">
        <p className="eyebrow">Maverick workspace app</p>
        <h1>{title}</h1>
        <p>This React/Vite app is mounted by Maverick and calls its own backend surface.</p>
      </section>
      <section className="status-panel">
        <h2>Status</h2>
        <pre>{{JSON.stringify(status, null, 2)}}</pre>
      </section>
    </main>
  );
}}
""",
        "frontend/src/main.tsx": """import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>
);
""",
        "frontend/src/styles.css": """:root {
  color-scheme: dark;
  background: #101113;
  color: #f5f5f5;
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
  background:
    radial-gradient(circle at top left, rgba(74, 222, 128, 0.16), transparent 32rem),
    linear-gradient(180deg, #17191d, #101113);
}

button,
input,
textarea,
select {
  color: inherit;
  font: inherit;
}

.app-shell {
  display: grid;
  gap: 1rem;
  width: min(960px, calc(100vw - 2rem));
  margin: 0 auto;
  padding: 2rem 0;
}

.hero,
.status-panel {
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.06);
  padding: 1.25rem;
}

.eyebrow {
  margin: 0 0 0.4rem;
  color: #9ae6b4;
  font-size: 0.72rem;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h1,
h2,
p {
  margin: 0;
}

h1 {
  margin-bottom: 0.65rem;
  font-size: clamp(2rem, 6vw, 3.8rem);
  line-height: 1;
}

h2 {
  margin-bottom: 0.75rem;
  font-size: 1rem;
}

p {
  color: rgba(245, 245, 245, 0.72);
  line-height: 1.5;
}

pre {
  overflow: auto;
  margin: 0;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.35);
  padding: 1rem;
  white-space: pre-wrap;
}
""",
        "frontend/dist/index.html": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>Run npm install and npm run build to refresh this React/Vite app.</p>
    </main>
  </body>
</html>
""",
    }
    if request.template_id == "widget":
        files.update(_react_widget_files(title))
    return files


def _node_runtime_check_script() -> str:
    return """#!/usr/bin/env node

const MINIMUM_NODE_VERSION = [24, 11, 0];
const SUPPORTED_NODE_MAJOR = 24;
const NODE_RUNTIME_REQUIREMENT = "Node.js 24 LTS (>=24.11.0 <25)";

function parseNodeVersion(value) {
  const match = value.trim().match(/\\bv?(\\d+)\\.(\\d+)\\.(\\d+)\\b/);
  if (!match) {
    return null;
  }
  return match.slice(1).map((part) => Number.parseInt(part, 10));
}

function formatNodeVersion(version) {
  return version.join(".");
}

function compareNodeVersion(left, right) {
  for (let index = 0; index < 3; index += 1) {
    if (left[index] !== right[index]) {
      return left[index] - right[index];
    }
  }
  return 0;
}

function nodeRuntimeDiagnostic(versionText) {
  const version = parseNodeVersion(versionText);
  if (!version) {
    return `node returned an unrecognized version \\`${versionText.trim()}\\``;
  }
  if (version[0] > SUPPORTED_NODE_MAJOR) {
    return `node ${formatNodeVersion(version)} is outside the supported range; Maverick requires ${NODE_RUNTIME_REQUIREMENT}`;
  }
  if (version[0] < SUPPORTED_NODE_MAJOR || compareNodeVersion(version, MINIMUM_NODE_VERSION) < 0) {
    return `node ${formatNodeVersion(version)} is too old; Maverick requires ${NODE_RUNTIME_REQUIREMENT}`;
  }
  return null;
}

const diagnostic = nodeRuntimeDiagnostic(process.version);
if (diagnostic) {
  console.error(diagnostic);
  process.exit(1);
}
"""


def _vite_config(app_id: str, *, include_widget: bool) -> str:
    if not include_widget:
        return f"""import {{ defineConfig }} from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({{
  plugins: [react()],
  base: '/apps/{app_id}/',
  root: 'frontend',
  build: {{
    outDir: 'dist',
    emptyOutDir: true
  }}
}});
"""
    return f"""import {{ resolve }} from 'node:path';
import {{ defineConfig }} from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({{
  plugins: [react()],
  base: '/apps/{app_id}/',
  root: 'frontend',
  build: {{
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {{
      input: {{
        app: resolve(__dirname, 'frontend/index.html'),
        widgetMain: resolve(__dirname, 'frontend/widgets/main/index.html')
      }}
    }}
  }}
}});
"""


def _react_widget_files(title: str) -> dict[str, str]:
    widget_title = f"{title} Widget"
    return {
        "frontend/widgets/main/index.html": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{widget_title}</title>
  </head>
  <body>
    <div id="widget-root"></div>
    <script type="module" src="/src/widgets/main/main.tsx"></script>
  </body>
</html>
""",
        "frontend/src/widgets/main/main.tsx": f"""import {{ StrictMode }} from 'react';
import {{ createRoot }} from 'react-dom/client';
import './styles.css';

function Widget() {{
  return (
    <main className="widget-shell">
      <strong>{widget_title}</strong>
      <p>React widget mounted through the Maverick widget surface.</p>
    </main>
  );
}}

createRoot(document.getElementById('widget-root')!).render(
  <StrictMode>
    <Widget />
  </StrictMode>
);
""",
        "frontend/src/widgets/main/styles.css": """:root {
  color-scheme: dark;
  background: transparent;
  color: #f5f5f5;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

body {
  margin: 0;
}

.widget-shell {
  display: grid;
  gap: 0.4rem;
  min-height: 100vh;
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: rgba(16, 17, 19, 0.94);
  padding: 0.85rem;
}

.widget-shell p {
  margin: 0;
  color: rgba(245, 245, 245, 0.66);
  font-size: 0.82rem;
  line-height: 1.35;
}
""",
        "frontend/dist/widgets/main/index.html": f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{widget_title}</title>
  </head>
  <body>
    <main>
      <strong>{widget_title}</strong>
      <p>Run npm install and npm run build to refresh this React/Vite widget.</p>
    </main>
  </body>
</html>
""",
    }
