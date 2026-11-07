import { useLanguage } from './language-context';
import { LANGUAGES, LANGUAGE_NAMES, isLanguage } from './languages';

const LABELS = { en: 'Language', he: 'שפה' } as const;

/** Small language switcher for the M2 screens; the choice stays in this browser only (Q13). */
export function LanguageSelector() {
  const { language, setLanguage } = useLanguage();
  return (
    <select
      aria-label={LABELS[language]}
      data-testid="language-selector"
      value={language}
      onChange={(event) => {
        if (isLanguage(event.target.value)) setLanguage(event.target.value);
      }}
      className="h-8 rounded-md border border-border bg-background px-2 text-sm"
    >
      {LANGUAGES.map((code) => (
        <option key={code} value={code} lang={code}>
          {LANGUAGE_NAMES[code]}
        </option>
      ))}
    </select>
  );
}
