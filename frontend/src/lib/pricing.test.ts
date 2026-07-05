import { afterEach, describe, expect, it, vi } from 'vitest';
import { formatPrice, PACKAGES, packageById, paymentsEnabled } from './pricing';

afterEach(() => {
  vi.unstubAllEnvs();
});

describe('pricing config', () => {
  it('carries the two placeholder anchor packages', () => {
    expect(PACKAGES.map((p) => p.id)).toEqual(['single_email', 'full_package']);
    expect(packageById('single_email')).toMatchObject({ amountCents: 990, currency: 'usd' });
    expect(packageById('full_package')).toMatchObject({ amountCents: 4900, currency: 'usd' });
    expect(packageById('nope')).toBeUndefined();
  });

  it('formats cents as dollars', () => {
    expect(formatPrice(990)).toBe('$9.90');
    expect(formatPrice(4900)).toBe('$49.00');
  });
});

describe('paymentsEnabled', () => {
  it('is off by default (unset flag)', () => {
    vi.stubEnv('NEXT_PUBLIC_PAYMENTS', '');
    expect(paymentsEnabled()).toBe(false);
  });

  it('is off for any non-truthy value', () => {
    vi.stubEnv('NEXT_PUBLIC_PAYMENTS', 'false');
    expect(paymentsEnabled()).toBe(false);
  });

  it('turns on for "true" and "1"', () => {
    vi.stubEnv('NEXT_PUBLIC_PAYMENTS', 'true');
    expect(paymentsEnabled()).toBe(true);
    vi.stubEnv('NEXT_PUBLIC_PAYMENTS', '1');
    expect(paymentsEnabled()).toBe(true);
  });
});
