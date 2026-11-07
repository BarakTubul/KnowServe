import { createContext, useContext } from 'react';
import { DEFAULT_LANGUAGE, type Language } from './languages';

export interface LanguageState {
  language: Language;
  dir: 'ltr' | 'rtl';
  setLanguage(language: Language): void;
}

/** Without a provider (isolated component tests) the interface is English. */
export const LanguageContext = createContext<LanguageState>({
  language: DEFAULT_LANGUAGE,
  dir: 'ltr',
  setLanguage: () => undefined,
});

export function useLanguage(): LanguageState {
  return useContext(LanguageContext);
}
