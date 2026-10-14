import { useEffect, useState } from 'react';
import { loopinoAppIsVisible, observeLoopinoVisibility } from '@loopino/pwa-cache';

export function useStorageVisibility(): boolean {
  const [visible, setVisible] = useState(loopinoAppIsVisible);
  useEffect(() => observeLoopinoVisibility(setVisible), []);
  return visible;
}
