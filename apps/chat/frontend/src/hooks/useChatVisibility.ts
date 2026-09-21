import { createContext, useContext, useEffect, useState } from 'react';
import { maverickAppIsVisible, observeMaverickVisibility } from '@maverick/pwa-cache';

export const ChatVisibilityContext = createContext(true);

export function useChatVisibility(): boolean {
  const surfaceVisible = useContext(ChatVisibilityContext);
  const [visible, setVisible] = useState(maverickAppIsVisible);
  useEffect(() => observeMaverickVisibility(setVisible), []);
  return visible && surfaceVisible;
}
