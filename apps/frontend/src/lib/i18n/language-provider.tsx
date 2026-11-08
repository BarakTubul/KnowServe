import { useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { LanguageContext } from './language-context';
import { directionOf, readStoredLanguage, storeLanguage, type Language } from './languages';

/** Holds the interface language, keeps `<html lang dir>` in step and remembers the choice (Q13). */
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(readStoredLanguage);
  const dir = directionOf(language);

  useEffect(() => {
    document.documentElement.lang = language;
    document.documentElement.dir = dir;
  }, [language, dir]);

  const setLanguage = useCallback((next: Language) => {
    setLanguageState(next);
    storeLanguage(next);
  }, []);

  const value = useMemo(() => ({ language, dir, setLanguage }), [language, dir, setLanguage]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}
