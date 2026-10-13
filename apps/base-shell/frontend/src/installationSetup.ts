import { mountInstallation } from '../../../../packages/installation-ui/src/view';
import { InstallationApiError, installationRequest } from '../../../../packages/installation-ui/src/api';
import '../../../../packages/installation-ui/src/styles.css';
import './installationSetup.css';

const root = document.getElementById('installation-root')!;
let view: ReturnType<typeof mountInstallation> | undefined;
try {
  const mode = JSON.parse(localStorage.getItem('maverick:base-shell:session') || '{}').themeMode;
  if (mode === 'light' || (mode === 'system' && matchMedia('(prefers-color-scheme: light)').matches)) document.documentElement.dataset.theme = 'light';
} catch { /* Start with the native dark theme. */ }
if (document.documentElement.dataset.theme === 'light') {
  document.getElementById('installation-brand')!.setAttribute('src', '/apps/base-shell/sidebar-logo-black.svg');
}

async function start() {
  try {
    await installationRequest('inspect');
    view = mountInstallation(root);
  } catch (error) {
    if (error instanceof InstallationApiError && error.status === 401) return signIn();
    root.className = 'installation-view';
    root.innerHTML = '<section class="installation-card"><h2>Administrator access required</h2><p>Sign in with a platform administrator to configure the installation.</p><a href="/">Open Maverick</a></section>';
  }
}
function signIn() {
  root.className = 'installation-view';
  if (!window.isSecureContext) {
    root.innerHTML = '<section class="installation-card"><h2>Use a secure connection</h2><p>Open setup over HTTPS or use a localhost tunnel to this server before signing in.</p></section>';
    return;
  }
  root.innerHTML = '<form class="installation-card"><p class="installation-eyebrow">Administrator sign in</p><h2>Set up your installation</h2><label class="installation-field">Username<input name="username" autocomplete="username" required></label><label class="installation-field">Password<input name="password" type="password" autocomplete="current-password" required></label><p data-login-error role="alert"></p><button class="installation-primary" type="submit">Sign in</button></form>';
  const form = root.querySelector('form')!;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const button = form.querySelector('button')!; button.disabled = true;
    const values = new FormData(form);
    try {
      const response = await fetch('/api/auth/login', { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(Object.fromEntries(values.entries())) });
      form.querySelector<HTMLInputElement>('[name=password]')!.value = '';
      if (response.ok) await start();
      else form.querySelector('[data-login-error]')!.textContent = 'Check your username and password.';
    } catch { form.querySelector('[data-login-error]')!.textContent = 'Unable to reach the server. Try again.'; }
    finally { button.disabled = false; }
  });
}
window.addEventListener('pagehide', () => { view?.destroy(); });
void start();
