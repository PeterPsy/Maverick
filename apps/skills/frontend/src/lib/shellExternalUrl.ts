import { requestParentExternalUrl } from '@maverick/pwa-cache';
import type { MouseEvent } from 'react';

export function openExternalLink(event: MouseEvent<HTMLAnchorElement>, url: string) {
  if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || event.button !== 0) return;
  if (requestParentExternalUrl(url)) event.preventDefault();
}
