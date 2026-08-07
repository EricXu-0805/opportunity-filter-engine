import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { normalizeProfileForRelease, RELEASE_SCOPE } from './release-scope';

describe('MVP public release scope', () => {
  it('fails closed for every unaccepted MTP or external-dependency feature', () => {
    expect(RELEASE_SCOPE).toEqual({
      matchAiRefine: false,
      crossSchoolMatching: false,
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

  it('removes stale Fellowship preferences at profile boundaries', () => {
    expect(
      normalizeProfileForRelease({
        seeking_types: ['research', 'fellowship'],
        major: 'Computer Science',
      }),
    ).toEqual({
      seeking_types: ['research'],
      major: 'Computer Science',
    });
  });

  it('removes stale cross-school matching preferences at profile boundaries', () => {
    expect(
      normalizeProfileForRelease({
        include_cross_school: true,
        major: 'Computer Science',
      }),
    ).toEqual({
      include_cross_school: false,
      major: 'Computer Science',
    });
  });
});
