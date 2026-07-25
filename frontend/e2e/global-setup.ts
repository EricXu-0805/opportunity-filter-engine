import { writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { STORAGE_KEYS } from '../src/lib/storage-keys';

// The first-visit onboarding tour (OnboardingIntro) is a full-viewport modal
// that intercepts every pointer event until dismissed — a fresh browser
// context therefore can't click anything and each click-based test burns its
// whole 30s timeout. Pre-seed the "tour seen" flag into the storageState every
// test context starts from; specs exercising the tour itself can opt back out
// with test.use({ storageState: undefined }).
export default function globalSetup(): void {
  const port = Number(process.env.E2E_PORT ?? 3100);
  const state = {
    cookies: [],
    origins: [
      {
        origin: `http://127.0.0.1:${port}`,
        localStorage: [
          { name: STORAGE_KEYS.ONBOARDING_SEEN, value: '1' },
          // W10b: the one-time school-confirm gate is the same kind of
          // full-viewport modal — pre-confirm the default campus so specs
          // (which never exercise the gate) aren't intercepted by it.
          {
            name: STORAGE_KEYS.SCHOOL_CONFIRMED,
            value: JSON.stringify({ slug: 'uiuc', ts: '2026-01-01T00:00:00.000Z' }),
          },
        ],
      },
    ],
  };
  writeFileSync(join(__dirname, '.storage-state.json'), JSON.stringify(state));
}
