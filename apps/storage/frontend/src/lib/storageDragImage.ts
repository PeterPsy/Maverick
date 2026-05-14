import type { DragEvent } from 'react';

const FOLDER_DRAG_ICON_SELECTOR = '.storage-folder-drag-icon-source';
const FALLBACK_FOLDER_ICON_SIZE = 24;

export function attachStorageFolderDragImage(event: DragEvent<HTMLElement>, movingCount = 1) {
  if (!event.dataTransfer.setDragImage) {
    return;
  }
  const source = event.currentTarget.querySelector<HTMLElement>(FOLDER_DRAG_ICON_SELECTOR);
  const icon = source ? folderIconElement(source) : null;
  if (!icon) {
    return;
  }

  const sourceStyle = window.getComputedStyle(icon);
  const sourceBounds = icon.getBoundingClientRect();
  const width = measuredIconSize(sourceBounds.width, sourceStyle.width);
  const height = measuredIconSize(sourceBounds.height, sourceStyle.height);
  const iconFrame = measuredIconFrame(icon, width, height);
  const dragImage = document.createElement('div');
  dragImage.style.position = 'fixed';
  dragImage.style.left = '-1000px';
  dragImage.style.top = '-1000px';
  dragImage.style.zIndex = '9999';
  dragImage.style.display = 'grid';
  dragImage.style.placeItems = 'center';
  dragImage.style.width = `${iconFrame.width}px`;
  dragImage.style.height = `${iconFrame.height}px`;
  dragImage.style.color = sourceStyle.color;
  dragImage.style.background = 'transparent';
  dragImage.style.overflow = 'visible';
  dragImage.style.pointerEvents = 'none';

  const clone = icon.cloneNode(true) as HTMLElement;
  if (iconFrame.viewBox && clone instanceof SVGElement) {
    clone.setAttribute('viewBox', iconFrame.viewBox);
  }
  clone.style.width = `${iconFrame.width}px`;
  clone.style.height = `${iconFrame.height}px`;
  clone.style.color = 'inherit';
  clone.style.display = 'block';
  clone.style.margin = '0';
  clone.style.padding = '0';
  dragImage.appendChild(clone);
  appendDragCountBadge(dragImage, movingCount);
  document.body.appendChild(dragImage);
  event.dataTransfer.setDragImage(dragImage, Math.round(iconFrame.width / 2), Math.round(iconFrame.height / 2));
  window.setTimeout(() => dragImage.remove(), 0);
}

function appendDragCountBadge(dragImage: HTMLElement, movingCount: number) {
  if (movingCount <= 1) {
    return;
  }
  const badge = document.createElement('span');
  badge.className = 'storage-drag-count-badge';
  badge.textContent = `+${movingCount}`;
  dragImage.appendChild(badge);
}

function folderIconElement(source: HTMLElement) {
  return source.matches('svg') ? source : source.querySelector<HTMLElement>('svg') || source;
}

function measuredIconSize(boundsValue: number, computedValue: string) {
  const parsed = Number.parseFloat(computedValue);
  if (Number.isFinite(boundsValue) && boundsValue > 0) {
    return Math.round(boundsValue);
  }
  if (Number.isFinite(parsed) && parsed > 0) {
    return Math.round(parsed);
  }
  return FALLBACK_FOLDER_ICON_SIZE;
}

function measuredIconFrame(icon: HTMLElement, renderedWidth: number, renderedHeight: number) {
  if (!(icon instanceof SVGSVGElement) || !icon.viewBox.baseVal.width || !icon.viewBox.baseVal.height) {
    return { width: renderedWidth, height: renderedHeight, viewBox: '' };
  }
  const box = svgGraphicBox(icon);
  if (!box || box.width <= 0 || box.height <= 0) {
    return { width: renderedWidth, height: renderedHeight, viewBox: '' };
  }
  const viewBox = icon.viewBox.baseVal;
  const strokePadding = 1.5;
  const cropped = {
    x: Math.max(viewBox.x, box.x - strokePadding),
    y: Math.max(viewBox.y, box.y - strokePadding),
    width: Math.min(viewBox.x + viewBox.width, box.x + box.width + strokePadding) - Math.max(viewBox.x, box.x - strokePadding),
    height: Math.min(viewBox.y + viewBox.height, box.y + box.height + strokePadding) - Math.max(viewBox.y, box.y - strokePadding),
  };
  return {
    width: Math.max(1, Math.round((cropped.width / viewBox.width) * renderedWidth)),
    height: Math.max(1, Math.round((cropped.height / viewBox.height) * renderedHeight)),
    viewBox: `${cropped.x} ${cropped.y} ${cropped.width} ${cropped.height}`,
  };
}

function svgGraphicBox(svg: SVGSVGElement): DOMRect | null {
  const graphics = Array.from(svg.querySelectorAll<SVGGraphicsElement>('circle, ellipse, line, path, polygon, polyline, rect'));
  let union: DOMRect | null = null;
  graphics.forEach((element) => {
    let box: DOMRect;
    try {
      box = element.getBBox();
    } catch {
      return;
    }
    if (!union) {
      union = box;
      return;
    }
    const left = Math.min(union.x, box.x);
    const top = Math.min(union.y, box.y);
    const right = Math.max(union.x + union.width, box.x + box.width);
    const bottom = Math.max(union.y + union.height, box.y + box.height);
    union = new DOMRect(left, top, right - left, bottom - top);
  });
  return union;
}
