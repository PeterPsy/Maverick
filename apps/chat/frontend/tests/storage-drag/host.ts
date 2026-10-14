import { installFrameReferenceDragBroker } from '../../../../base-shell/frontend/src/lib/frameReferenceDragBroker';
import { LOOPINO_IFRAME_SANDBOX, setLoopinoFrameOrigin } from '../../../../base-shell/frontend/src/iframePolicy';
import '../../../../base-shell/frontend/src/styles/ui.css';

const scope = { workspaceId: 'fixture', sessionGeneration: 'fixture-login' };
installFrameReferenceDragBroker(scope);
for (const id of ['storage', 'sidebar', 'chat']) {
  const frame = document.getElementById(id) as HTMLIFrameElement;
  const url = new URL(location.href);
  url.hostname = `${id}.localhost`;
  url.pathname = id === 'chat' ? '/apps/chat/tests/composer/index.html' : '/apps/chat/tests/storage-drag/source.html';
  url.searchParams.set('shell_origin', location.origin);
  url.searchParams.set('widget', 'true');
  url.searchParams.set('width', '480');
  if (id === 'sidebar') url.searchParams.set('mode', 'sidebar');
  frame.sandbox.value = LOOPINO_IFRAME_SANDBOX;
  frame.src = url.href;
  setLoopinoFrameOrigin(frame, url.origin, id === 'chat' ? 'chat' : 'storage', scope);
}
