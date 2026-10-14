import { createContext, useContext, useEffect, useState } from 'react';
import { loopinoAppIsVisible, observeLoopinoVisibility } from '@loopino/pwa-cache';

export const ChatVisibilityContext = createContext(true);

export function useChatVisibility(): boolean {
  const surfaceVisible = useContext(ChatVisibilityContext);
  const [visible, setVisible] = useState(loopinoAppIsVisible);
  useEffect(() => observeLoopinoVisibility(setVisible), []);
  return visible && surfaceVisible;
}
