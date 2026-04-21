"""React/Vite template files for SDK-generated apps."""

from __future__ import annotations

from core.app_sdk.models import AppSdkCreateRequest
from core.app_sdk.template_common import title_from_slug


def react_vite_files(request: AppSdkCreateRequest) -> dict[str, str]:
    """Return React/Vite source plus a committed dist smoke build."""
    title = request.name or title_from_slug(request.app_id)
    app_id = request.app_id
    return {
        "package.json": f'''{{
  "name": "{app_id}",
  "version": "{request.version}",
  "private": true,
  "type": "module",
  "scripts": {{
    "build": "vite"
  }},
  "dependencies": {{
    "@vitejs/plugin-react": "^5.0.0",
    "vite": "^7.0.0",
    "typescript": "^5.0.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0"
  }},
  "devDependencies": {{}}
}}
''',
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
        "vite.config.ts": """import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  root: 'frontend',
  build: {
    outDir: 'dist',
    emptyOutDir: true
  }
});
""",
        "frontend/index.html": f"""<!doctype html>
<html>
  <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>{title}</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
""",
        "frontend/src/main.tsx": f"""import React, {{ useEffect, useState }} from 'react';
import {{ createRoot }} from 'react-dom/client';
import './styles.css';

type Status = {{ app_id?: string; status?: string; [key: string]: unknown }};

async function callBackend(body: Record<string, unknown>): Promise<Status> {{
  const response = await fetch('/api/apps/{app_id}/backend', {{
    method: 'POST',
    headers: {{ 'Content-Type': 'application/json' }},
    body: JSON.stringify(body)
  }});
  return response.json();
}}

function App() {{
  const [status, setStatus] = useState<Status>({{}});
  useEffect(() => {{
    callBackend({{ action: 'status' }}).then(setStatus).catch((error) => setStatus({{ status: String(error) }}));
  }}, []);
  return (
    <main>
      <h1>{title}</h1>
      <section>
        <h2>Status</h2>
        <pre>{{JSON.stringify(status, null, 2)}}</pre>
      </section>
    </main>
  );
}}

createRoot(document.getElementById('root')!).render(<App />);
""",
        "frontend/src/styles.css": """body {
  margin: 0;
  background: #0f172a;
  color: #f8fafc;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

main {
  max-width: 960px;
  margin: 0 auto;
  padding: 32px;
}

section {
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 16px;
  background: #111827;
}

pre {
  white-space: pre-wrap;
}
""",
        "frontend/dist/index.html": f"""<!doctype html>
<html>
  <head><meta charset="utf-8"><title>{title}</title></head>
  <body><main><h1>{title}</h1><p>Run npm install and npm run build to refresh this React/Vite app.</p></main></body>
</html>
""",
    }
