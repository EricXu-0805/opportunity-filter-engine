import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';

const config = [
  {
    ignores: [
      '.next/**',
      'node_modules/**',
      'public/**',
      'out/**',
      'e2e/**',
      'playwright-report/**',
      'test-results/**',
      'src/lib/api-types.gen.ts',
      'next-env.d.ts',
    ],
  },
  ...nextCoreWebVitals,
  {
    rules: {
      '@next/next/no-img-element': 'off',
      'react/no-unescaped-entities': 'warn',
      // eslint-plugin-react-hooks v7 (auto-installed by eslint-config-next 16)
      // introduced this strict rule. ~21 legitimate "init from prop /
      // localStorage on mount" usages currently violate it; converting them
      // to useSyncExternalStore / derived state is its own refactor and
      // out of scope for the Next 16 upgrade. Tracked as a Round 9 cleanup.
      'react-hooks/set-state-in-effect': 'warn',
    },
  },
];

export default config;
