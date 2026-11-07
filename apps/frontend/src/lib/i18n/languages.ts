/** Interface languages (Q13, OPEN-29): English is the default, Hebrew is right-to-left. */
export const LANGUAGES = ['en', 'he'] as const;
export type Language = (typeof LANGUAGES)[number];
export const DEFAULT_LANGUAGE: Language = 'en';
export const LANGUAGE_STORAGE_KEY = 'knowserve.locale';

/** Each language is named in itself, so a reader can find theirs in any interface language. */
export const LANGUAGE_NAMES: Record<Language, string> = { en: 'English', he: 'עברית' };

export function isLanguage(value: unknown): value is Language {
  return typeof value === 'string' && (LANGUAGES as readonly string[]).includes(value);
}

export function directionOf(language: Language): 'ltr' | 'rtl' {
  return language === 'he' ? 'rtl' : 'ltr';
}

/** The choice kept in this browser; blocked, missing or unknown values fall back to English. */
export function readStoredLanguage(): Language {
  try {
    const stored = globalThis.localStorage?.getItem(LANGUAGE_STORAGE_KEY);
    if (isLanguage(stored)) return stored;
  } catch {
    // Storage can be blocked; English is fine.
  }
  return DEFAULT_LANGUAGE;
}

export function storeLanguage(language: Language): void {
  try {
    globalThis.localStorage?.setItem(LANGUAGE_STORAGE_KEY, language);
  } catch {
    // The choice still applies for this visit.
  }
}

/**
 * Text for an error code: the selected language, then English for a code the language lacks, then the
 * language's generic message. Raw API text never reaches the screen (FE-ARCH-14, PROD-13).
 */
export function messageForCode(
  errors: Record<string, string> & { generic: string },
  englishErrors: Record<string, string> & { generic: string },
  code: string,
): string {
  if (code !== 'generic') {
    const own = Object.hasOwn(errors, code) ? errors[code] : undefined;
    if (own) return own;
    const english = Object.hasOwn(englishErrors, code) ? englishErrors[code] : undefined;
    if (english) return english;
  }
  return errors.generic;
}
