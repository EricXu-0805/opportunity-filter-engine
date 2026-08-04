/*
 * W14: the UNCONFIGURED-Supabase contract (the designed local-only mode the
 * E2E environment runs in, disclosed by the storage banner). Degraded mode
 * is NOT failure:
 *
 *   - getInteractionsFull resolves an empty Map (genuinely zero synced rows)
 *   - trackInteraction no-op resolves (client state carries the session)
 *   - updateInteractionDetails resolves true (no sync exists to claim)
 *
 * The configured-but-failing contracts (throw / false) live in
 * supabase-interactions.test.ts. Together they pin the split: designed
 * degraded mode ≠ failure.
 */

import { describe, expect, it, vi } from 'vitest';

vi.hoisted(() => {
  delete process.env.NEXT_PUBLIC_SUPABASE_URL;
  delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
});

import {
  getInteractionsFull,
  trackInteraction,
  updateInteractionDetails,
} from './supabase';

describe('unconfigured Supabase = designed local-only mode, not failure', () => {
  it('getInteractionsFull resolves empty instead of throwing', async () => {
    const map = await getInteractionsFull();
    expect(map.size).toBe(0);
  });

  it('trackInteraction no-op resolves', async () => {
    await expect(trackInteraction('opp-1', 'applied')).resolves.toBeUndefined();
  });

  it('updateInteractionDetails resolves true (banner owns the disclosure)', async () => {
    await expect(updateInteractionDetails('opp-1', { notes: 'x' })).resolves.toBe(true);
  });
});
