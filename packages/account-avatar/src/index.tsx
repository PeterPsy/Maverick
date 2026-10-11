import { useState, type ReactNode } from 'react';

export function googlePictureUrl(value?: string): string {
  if (!value || value.length > 4096 || /[\s\\\u0000-\u001f]/.test(value)) return '';
  try {
    const url = new URL(value);
    return url.protocol === 'https:' && url.hostname.endsWith('.googleusercontent.com')
      && (!url.port || url.port === '443') && !url.username && !url.password && !url.hash ? value : '';
  } catch { return ''; }
}

/** Decorative account photo; the adjacent account label supplies its identity. */
export function AccountAvatar({ pictureUrl, fallback, size = 22 }: {
  pictureUrl?: string;
  fallback: ReactNode;
  size?: number;
}) {
  const src = googlePictureUrl(pictureUrl);
  const [failedSrc, setFailedSrc] = useState('');
  const [loadedSrc, setLoadedSrc] = useState('');
  return <span aria-hidden="true" style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
    position: 'relative', flex: '0 0 auto', width: size, height: size, borderRadius: '50%', overflow: 'hidden' }}>
    {(!src || failedSrc === src || loadedSrc !== src) && fallback}
    {src && failedSrc !== src && <img key={src} src={src} alt="" referrerPolicy="no-referrer" decoding="async"
      onError={() => setFailedSrc(src)} onLoad={() => setLoadedSrc(src)}
      style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover',
        borderRadius: 'inherit', opacity: loadedSrc === src ? 1 : 0 }} />}
  </span>;
}
