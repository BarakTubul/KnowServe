import { describe, expect, it } from 'vitest';
import { LANGUAGES } from '@/lib/i18n/languages';
import {
  ADMIN_ERROR_CATALOGS,
  FAILURE_CATALOGS,
  adminErrorMessage,
  failureMessage,
} from './admin-error-messages';

const HEBREW = /[֐-׿]/;

describe('Admin error catalogs (PROD-13, OPEN-31 D8)', () => {
  it('has the same codes in English and Hebrew', () => {
    expect(Object.keys(ADMIN_ERROR_CATALOGS.he).sort()).toEqual(
      Object.keys(ADMIN_ERROR_CATALOGS.en).sort(),
    );
    expect(Object.keys(FAILURE_CATALOGS.he).sort()).toEqual(
      Object.keys(FAILURE_CATALOGS.en).sort(),
    );
  });

  it.each(LANGUAGES)('has a non-empty, non-technical message for every code in %s', (language) => {
    for (const catalog of [ADMIN_ERROR_CATALOGS[language], FAILURE_CATALOGS[language]]) {
      for (const [code, message] of Object.entries(catalog)) {
        expect(message.length, code).toBeGreaterThan(8);
        expect(message, code).not.toMatch(/exception|traceback|stack|null|undefined|\bHTTP\b/i);
        expect(message, code).not.toContain(code); // the code is never the text
      }
    }
  });

  it('writes the Hebrew catalog in Hebrew', () => {
    for (const message of Object.values(ADMIN_ERROR_CATALOGS.he)) expect(message).toMatch(HEBREW);
    for (const message of Object.values(FAILURE_CATALOGS.he)) expect(message).toMatch(HEBREW);
  });

  it('answers in the selected language, falls back to generic for an unknown code', () => {
    expect(adminErrorMessage('UPLOADS_DISABLED', 'en')).toMatch(/paused/i);
    expect(adminErrorMessage('UPLOADS_DISABLED', 'he')).toMatch(HEBREW);
    expect(failureMessage('NO_EXTRACTABLE_TEXT', 'en')).toMatch(/selectable text/i);
    expect(adminErrorMessage('SOMETHING_NEW', 'en')).toBe(ADMIN_ERROR_CATALOGS.en.generic);
    expect(adminErrorMessage('SOMETHING_NEW', 'he')).toBe(ADMIN_ERROR_CATALOGS.he.generic);
    expect(failureMessage('SOMETHING_NEW', 'he')).toBe(FAILURE_CATALOGS.he.generic);
  });
});
