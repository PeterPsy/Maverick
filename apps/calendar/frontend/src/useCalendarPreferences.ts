import { useEffect, useState } from 'react';
import { readPreferences } from './preferences';

export function useCalendarPreferences() {
  const [preferences, setPreferences] = useState(readPreferences);
  useEffect(() => {
    const update = () => setPreferences(readPreferences());
    window.addEventListener('calendar-preferences-changed', update);
    window.addEventListener('storage', update);
    return () => {
      window.removeEventListener('calendar-preferences-changed', update);
      window.removeEventListener('storage', update);
    };
  }, []);
  return preferences;
}
