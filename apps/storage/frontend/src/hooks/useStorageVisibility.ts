import { useEffect, useState } from 'react';
import { maverickAppIsVisible, observeMaverickVisibility } from '@maverick/pwa-cache';

export function useStorageVisibility(): boolean {
  const [visible, setVisible] = useState(maverickAppIsVisible);
  useEffect(() => observeMaverickVisibility(setVisible), []);
  return visible;
}
