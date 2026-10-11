import { installFrameReferenceDragBroker } from '../../../../base-shell/frontend/src/lib/frameReferenceDragBroker';
import { MAVERICK_IFRAME_SANDBOX, setMaverickFrameOrigin } from '../../../../base-shell/frontend/src/iframePolicy';
import '../../../../base-shell/frontend/src/styles/ui.css';

const scope = { workspaceId: 'fixture', sessionGeneration: 'fixture-login' };
installFrameReferenceDragBroker(scope);
for (const appId of ['mail', 'chat']) {
  const frame = document.getElementById(appId) as HTMLIFrameElement;
  const url = new URL(location.href);
  url.hostname = `${appId}.localhost`;
  url.pathname = appId === 'mail' ? '/apps/chat/tests/mail-drag/source.html' : '/apps/chat/tests/composer/index.html';
  url.search = new URLSearchParams({ shell_origin: location.origin, widget: 'true', width: '480' }).toString();
  frame.sandbox.value = MAVERICK_IFRAME_SANDBOX;
  frame.src = url.href;
  setMaverickFrameOrigin(frame, url.origin, appId, scope);
}
