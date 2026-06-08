export type PreviewMediaSize = {
  width: number;
  height: number;
};

export function fitPreviewMediaToBox(media: PreviewMediaSize, box: PreviewMediaSize) {
  if (media.width <= 0 || media.height <= 0 || box.width <= 0 || box.height <= 0) return null;
  const scale = Math.min(box.width / media.width, box.height / media.height);
  if (!Number.isFinite(scale) || scale <= 0) return null;
  return {
    width: Math.max(1, Math.floor(media.width * scale)),
    height: Math.max(1, Math.floor(media.height * scale))
  };
}
