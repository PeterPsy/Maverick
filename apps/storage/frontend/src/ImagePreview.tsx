import { useEffect, useRef, useState } from 'react';
import { fitPreviewMediaToBox, type PreviewMediaSize } from './previewSizing';
import './styles/image-preview.css';

export function ImagePreview({ src, name }: { src: string; name: string }) {
  const frameRef = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState<PreviewMediaSize | null>(null);
  const [natural, setNatural] = useState<PreviewMediaSize | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => { setNatural(null); setFailed(false); }, [src]);
  useEffect(() => {
    const frame = frameRef.current;
    if (!frame) return;
    const resize = () => {
      const rect = frame.getBoundingClientRect();
      setBox({ width: Math.floor(rect.width), height: Math.floor(rect.height) });
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(frame);
    return () => observer.disconnect();
  }, []);
  const size = natural && box ? fitPreviewMediaToBox(natural, {
    width: Math.min(box.width, natural.width), height: Math.min(box.height, natural.height),
  }) : null;
  return <div className="storage-image-preview" ref={frameRef}>
    {failed ? <p role="alert">Unable to load this image. Close the preview and try again.</p>
      : <img src={src} alt={name} draggable={false}
          style={size ? { width: `${size.width}px`, height: `${size.height}px` } : undefined}
          onLoad={(event) => setNatural({ width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight })}
          onError={() => setFailed(true)} />}
  </div>;
}
