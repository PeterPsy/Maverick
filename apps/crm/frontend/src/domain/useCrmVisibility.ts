import { useEffect, useState } from 'react';
import { loopinoAppIsVisible, observeLoopinoVisibility } from '@loopino/pwa-cache';

export function useCrmVisibility(requireOnline = true): boolean {
  const [visible, setVisible] = useState(() => loopinoAppIsVisible({ requireOnline }));
  useEffect(() => observeLoopinoVisibility(setVisible, { requireOnline }), [requireOnline]);
  return visible;
}
