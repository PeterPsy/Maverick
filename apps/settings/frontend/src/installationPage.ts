import { mountInstallation } from '../../../../packages/installation-ui/src/view';
import '../../../../packages/installation-ui/src/styles.css';

export function createInstallationPage() {
  let element: HTMLElement | null = null;
  let view: ReturnType<typeof mountInstallation> | undefined;
  return {
    attach(next: HTMLElement | null) {
      if (element === next) return;
      view?.destroy();
      element = next;
      view = next ? mountInstallation(next) : undefined;
    },
  };
}
