import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import {
  CATALOGS,
  libraryCatalog,
  libraryErrorMessage,
} from '@/features/documents/library-messages';
import {
  VIEWER_CATALOGS,
  viewerCatalog,
  viewerMessage,
} from '@/features/documents/viewer/messages';
import { ApiError } from '@/lib/api/errors';
import {
  DEPARTMENTS,
  DEPARTMENTS_LIST,
  ME,
  departmentsOk,
  jsonResponse,
  makeIdentity,
  mockApi,
} from '@/test/fake-api';
import { renderApp } from '@/test/render';
import { useLanguage } from './language-context';
import { LanguageProvider } from './language-provider';
import { LanguageSelector } from './language-selector';
import { LANGUAGES, LANGUAGE_STORAGE_KEY, messageForCode, readStoredLanguage } from './languages';

function Probe() {
  const { language, dir } = useLanguage();
  return (
    <output data-testid="probe">
      {language}/{dir}
    </output>
  );
}

function renderSelector() {
  return render(
    <LanguageProvider>
      <LanguageSelector />
      <Probe />
    </LanguageProvider>,
  );
}

describe('Q13 language state (FE-ARCH-14, M2-AC22)', () => {
  it('q13_defaults_to_english_ltr_and_sets_html_lang_and_dir', () => {
    renderSelector();
    expect(screen.getByTestId('probe')).toHaveTextContent('en/ltr');
    expect(document.documentElement.lang).toBe('en');
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('q13_selector_switches_language_dir_and_persists_in_the_browser', async () => {
    const user = userEvent.setup();
    const first = renderSelector();
    await user.selectOptions(screen.getByTestId('language-selector'), 'he');
    expect(screen.getByTestId('probe')).toHaveTextContent('he/rtl');
    expect(document.documentElement.lang).toBe('he');
    expect(document.documentElement.dir).toBe('rtl');
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('he');
    first.unmount();
    renderSelector();
    expect(screen.getByTestId('probe')).toHaveTextContent('he/rtl');
    expect(screen.getByRole('combobox', { name: 'שפה' })).toHaveValue('he');
  });

  it('q13_an_unknown_stored_value_falls_back_to_english', () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'xx');
    expect(readStoredLanguage()).toBe('en');
  });

  it('q13_blocked_storage_still_renders_and_switches_for_the_visit', async () => {
    const user = userEvent.setup();
    const fail = () => {
      throw new Error('blocked');
    };
    vi.stubGlobal('localStorage', { getItem: fail, setItem: fail });
    renderSelector();
    expect(screen.getByTestId('probe')).toHaveTextContent('en/ltr');
    await user.selectOptions(screen.getByTestId('language-selector'), 'he');
    expect(screen.getByTestId('probe')).toHaveTextContent('he/rtl');
  });
});

describe('Q13 screens follow the selected language', () => {
  const pageOne = {
    items: [
      {
        id: '00000000-0000-4000-8000-000000000001',
        title: 'Handbook',
        filename: 'handbook.pdf',
        page_count: 2,
        owner_department: DEPARTMENTS[0],
      },
    ],
    has_more: false,
    next_cursor: null,
  };

  function api(body: object) {
    mockApi({
      [ME]: () => jsonResponse(200, makeIdentity({ active_department: DEPARTMENTS[0] })),
      [DEPARTMENTS_LIST]: departmentsOk,
      'GET /v1/documents': () => jsonResponse(200, body),
    });
  }

  it('q13_library_switches_text_and_direction_from_the_selector', async () => {
    api(pageOne);
    const { user } = renderApp('/documents');
    expect(await screen.findByRole('heading', { name: 'Documents' })).toBeInTheDocument();
    await user.selectOptions(screen.getByTestId('language-selector'), 'he');
    expect(await screen.findByRole('heading', { name: 'מסמכים' })).toBeInTheDocument();
    expect(await screen.findByText(CATALOGS.he.pages(2), { exact: false })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('rtl');
    await user.selectOptions(screen.getByTestId('language-selector'), 'en');
    expect(await screen.findByRole('heading', { name: 'Documents' })).toBeInTheDocument();
    expect(document.documentElement.dir).toBe('ltr');
  });

  it('q13_a_saved_hebrew_choice_opens_the_library_in_hebrew', async () => {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, 'he');
    api({ ...pageOne, items: [] });
    renderApp('/documents');
    expect(await screen.findByTestId('library-empty')).toHaveTextContent(CATALOGS.he.empty);
  });
});

const SAMPLE_NAME = 'מכירות';
const LATIN = /[A-Za-z]/;

function plainTexts(catalog: object): string[] {
  const out: string[] = [];
  for (const [key, value] of Object.entries(catalog)) {
    if (key === 'errors') continue;
    if (typeof value === 'string') out.push(value);
    else if (typeof value === 'function') out.push(String(value(2, 5)));
  }
  return out;
}

describe('Q13 catalogs (FE-ARCH-14, PROD-13)', () => {
  it('q13_every_language_has_every_library_and_viewer_error_code_and_ui_string', () => {
    for (const all of [CATALOGS, VIEWER_CATALOGS] as const) {
      const base = all.en;
      for (const language of LANGUAGES) {
        const other = all[language];
        expect(Object.keys(other).sort()).toEqual(Object.keys(base).sort());
        expect(Object.keys(other.errors).sort()).toEqual(Object.keys(base.errors).sort());
        for (const message of Object.values(other.errors)) expect(message.trim()).not.toBe('');
      }
    }
  });

  it('q13_hebrew_messages_have_no_technical_or_english_text', () => {
    for (const catalog of [CATALOGS.he, VIEWER_CATALOGS.he]) {
      for (const message of Object.values(catalog.errors)) {
        expect(message).not.toMatch(LATIN);
        expect(message).not.toMatch(/\d/);
      }
    }
    for (const text of [...plainTexts(CATALOGS.he), ...plainTexts(VIEWER_CATALOGS.he)]) {
      expect(text).not.toMatch(LATIN);
    }
    expect(CATALOGS.he.ownerDepartment(SAMPLE_NAME)).toContain(SAMPLE_NAME);
  });

  it('q13_english_error_messages_have_no_status_codes_or_technical_words', () => {
    for (const catalog of [CATALOGS.en, VIEWER_CATALOGS.en]) {
      for (const message of Object.values(catalog.errors)) {
        expect(message).not.toMatch(/\b[45]\d\d\b|stack|trace|exception|[A-Z]+_[A-Z_]+/i);
      }
    }
  });

  it('q13_an_unknown_code_uses_the_generic_message_in_each_language', () => {
    const error = new ApiError({ code: 'SOMETHING_NEW', message: 'raw detail', status: 500 });
    for (const language of LANGUAGES) {
      expect(libraryErrorMessage(error, libraryCatalog(language))).toBe(
        CATALOGS[language].errors.generic,
      );
      expect(viewerMessage('SOMETHING_NEW', viewerCatalog(language))).toBe(
        VIEWER_CATALOGS[language].errors.generic,
      );
    }
    expect(viewerMessage('constructor')).toBe(VIEWER_CATALOGS.en.errors.generic);
  });

  it('q13_a_code_missing_in_one_language_falls_back_to_english_then_generic', () => {
    const en = { generic: 'G', KNOWN: 'known english' };
    const partial = { generic: 'ג' };
    expect(messageForCode(partial, en, 'KNOWN')).toBe('known english');
    expect(messageForCode(partial, en, 'OTHER')).toBe('ג');
  });

  it('q13_an_unknown_language_gets_the_english_catalog', () => {
    expect(libraryCatalog('xx')).toBe(CATALOGS.en);
    expect(viewerCatalog('xx')).toBe(VIEWER_CATALOGS.en);
  });
});
