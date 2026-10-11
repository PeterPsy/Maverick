// @vitest-environment happy-dom
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it } from 'vitest';
import { AccountAvatar, googlePictureUrl } from '@maverick/account-avatar';

it('keeps a fallback while loading, on errors and when changing accounts', () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const element = document.createElement('div');
  const root = createRoot(element);
  const first = 'https://lh3.googleusercontent.com/a/first';
  const second = 'https://lh3.googleusercontent.com/a/second';
  try {
    act(() => root.render(<AccountAvatar pictureUrl={first} fallback={<span>Account icon</span>} />));
    expect(element.textContent).toContain('Account icon');
    expect(element.querySelector('img')?.referrerPolicy).toBe('no-referrer');
    act(() => element.querySelector('img')!.dispatchEvent(new Event('load')));
    expect(element.textContent).not.toContain('Account icon');
    act(() => root.render(<AccountAvatar pictureUrl={second} fallback={<span>Account icon</span>} />));
    expect(element.textContent).toContain('Account icon');
    expect(element.querySelector('img')?.src).toBe(second);
    act(() => element.querySelector('img')!.dispatchEvent(new Event('error')));
    expect(element.querySelector('img')).toBeNull();
    expect(element.textContent).toContain('Account icon');
    act(() => root.render(<AccountAvatar pictureUrl={first} fallback={<span>Account icon</span>} />));
    expect(element.querySelector('img')?.src).toBe(first);
  } finally { act(() => root.unmount()); }
});

it('rejects non-Google URLs, credentials and active content', () => {
  for (const url of ['javascript:alert(1)', 'data:image/svg+xml,x', 'http://lh3.googleusercontent.com/a',
    'https://lh3.googleusercontent.com.evil.test/a', 'https://user@lh3.googleusercontent.com/a',
    'https://lh3.googleusercontent.com:9000/a', 'https://lh3.googleusercontent.com/a#x']) {
    expect(googlePictureUrl(url)).toBe('');
  }
});
