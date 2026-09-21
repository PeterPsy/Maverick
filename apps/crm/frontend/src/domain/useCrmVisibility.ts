import { useEffect, useState } from 'react';
import { maverickAppIsVisible, observeMaverickVisibility } from '@maverick/pwa-cache';

export function useCrmVisibility(requireOnline = true): boolean {
  const [visible, setVisible] = useState(() => maverickAppIsVisible({ requireOnline }));
  useEffect(() => observeMaverickVisibility(setVisible, { requireOnline }), [requireOnline]);
  return visible;
}
