// ESLint baseline (flat config): the recommended JavaScript and TypeScript rules plus the two classic React Hooks rules.
// Formatting is not linted: the code base keeps its own dense style and Prettier is not used. Type-aware rules are limited to the
// two that catch real asynchronous mistakes. Run from `frontend`: `npm run lint`.
import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'test-results', 'playwright-report', 'coverage'] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  { rules: { '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' }] } },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { globals: globals.browser, parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'warn',
      '@typescript-eslint/no-floating-promises': 'error',
      '@typescript-eslint/no-misused-promises': ['error', { checksVoidReturn: { attributes: false } }],
    },
  },
  {
    files: ['tests/**/*.ts', '*.config.{ts,js}'],
    languageOptions: { globals: globals.node },
    // Playwright helpers pass locators and pages loosely; the existing uses are a warning backlog, new ones are visible in every run.
    rules: { '@typescript-eslint/no-explicit-any': 'warn' },
  },
  { files: ['public/**/*.js'], languageOptions: { globals: globals.browser } },
)
