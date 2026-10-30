import js from '@eslint/js';
import reactHooks from 'eslint-plugin-react-hooks';
import globals from 'globals';
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist', 'src/lib/api/schema.d.ts', 'playwright-report', 'test-results', '.wrangler'],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx,js,mjs}'],
    languageOptions: { globals: { ...globals.browser, ...globals.node } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // FE-ARCH-08: no ad-hoc inline styles; use Tailwind classes and design tokens.
      'no-restricted-syntax': [
        'error',
        {
          selector: "JSXAttribute[name.name='style']",
          message:
            'Inline style attributes are forbidden (FE-ARCH-08). Use Tailwind classes and tokens.',
        },
      ],
    },
  },
);
