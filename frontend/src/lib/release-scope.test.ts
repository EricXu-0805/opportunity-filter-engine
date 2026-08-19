import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  normalizeProfileForRelease,
  PUBLIC_RELEASE_CACHE_VERSION,
  RELEASE_SCOPE,
} from './release-scope';

describe('MVP public release scope', () => {
  it('is exactly the accepted table, so a flip is never a side effect', () => {
    // The three still-closed switches are closed for reasons outside this
    // codebase, not because the feature is unfinished:
    //   microsoftSchoolAuth — Azure publisher verification needs a verified
    //     legal entity, and without it students see an "unverified publisher"
    //     consent screen. Google sign-in is live.
    //   payments / conciergePayQr — pricing.ts and public/pay/*.png are not on
    //     main, and migration 026 dropped the orders RLS policies and revoked
    //     anon/authenticated access. The flag is not the missing part.
    expect(RELEASE_SCOPE).toEqual({
      matchAiRefine: false,
      crossSchoolMatching: true,
      compare: false,
      resumeRenovate: false,
      fellowships: false,
      roadmap: false,
      askAi: false,
      professorSignals: false,
      microsoftSchoolAuth: false,
      payments: false,
      conciergePayQr: false,
    });
  });

  it('cannot be mutated at runtime', () => {
    expect(Object.isFrozen(RELEASE_SCOPE)).toBe(true);
  });

  it('does not publish real payment codes before the commercial contract is accepted', () => {
    expect(existsSync(resolve('public/pay/wechat.png'))).toBe(false);
    expect(existsSync(resolve('public/pay/alipay.png'))).toBe(false);
  });

  it('keeps placeholder packages and order capabilities out of the public client source', () => {
    expect(existsSync(resolve('src/lib/pricing.ts'))).toBe(false);
    const publicClientSource = [
      'src/app/account/page.tsx',
      'src/lib/supabase.ts',
      'src/i18n/dictionaries.ts',
    ].map((path) => readFileSync(resolve(path), 'utf8')).join('\n');

    expect(publicClientSource).not.toContain('/pay/wechat.png');
    expect(publicClientSource).not.toContain('/pay/alipay.png');
    expect(publicClientSource).not.toContain("from('orders')");
    expect(publicClientSource).not.toContain('amountCents: 990');
    expect(publicClientSource).not.toContain('amountCents: 4900');
  });

  it('strips hidden fellowships while preserving accepted cross-school matching', () => {
    // The enforced boundary is the server's, not this one: a client that never
    // ran this still cannot smuggle a hidden preference past
    // matches._normalized_profile (tests/test_release_scope.py). This function
    // only keeps a stale local profile from re-showing a selector.
    expect(
      normalizeProfileForRelease({
        seeking_types: ['research', 'fellowship', ' Fellowship ', 'FELLOWSHIP'],
        include_cross_school: true,
        major: 'Computer Science',
      }),
    ).toEqual({
      seeking_types: ['research'],
      include_cross_school: true,
      major: 'Computer Science',
    });
  });

  it('pins a new public cache namespace for the closed capability surface', () => {
    expect(PUBLIC_RELEASE_CACHE_VERSION).toBe(
      'mvp-core-close-v1-contact-trust-v1-faculty-trust-v1',
    );
  });
});
