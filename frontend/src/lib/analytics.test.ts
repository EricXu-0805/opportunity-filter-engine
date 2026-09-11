/* @vitest-environment jsdom */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const insert = vi.fn();
const getDeviceId = vi.fn();

vi.mock('./supabase', () => ({
  supabase: { from: () => ({ insert }) },
  getDeviceId: () => getDeviceId(),
}));

import { track, trackOnce } from './analytics';
import { advanceOwnerEpoch, captureOwnerToken, isLocalOwnerReady, syncLocalIdentityOwner } from './identity-owner';

describe('track', () => {
  beforeEach(() => {
    insert.mockReset().mockResolvedValue({ error: null });
    getDeviceId.mockReset().mockResolvedValue('dev-1');
    sessionStorage.clear();
  });

  it('inserts an event row with device_id, event and props', async () => {
    await track('match_opened', { opportunity_id: 'opp-9' });
    expect(insert).toHaveBeenCalledWith({
      device_id: 'dev-1',
      event: 'match_opened',
      props: { opportunity_id: 'opp-9' },
    });
  });

  it('no-ops (no insert) when there is no device id', async () => {
    getDeviceId.mockResolvedValue(null);
    await track('landing_view');
    expect(insert).not.toHaveBeenCalled();
  });

  it('never throws when the insert rejects — analytics is best-effort', async () => {
    insert.mockRejectedValue(new Error('offline'));
    await expect(track('ai_feature_used', { feature: 'chat' })).resolves.toBeUndefined();
  });
});

describe('track — bound to the account on screen when the event fired', () => {
  async function claimOwner(uid: string): Promise<void> {
    advanceOwnerEpoch(uid);
    await syncLocalIdentityOwner(uid);
    for (let i = 0; i < 200 && !isLocalOwnerReady(uid); i += 1) await new Promise((r) => setTimeout(r, 0));
    expect(isLocalOwnerReady(uid)).toBe(true);
  }

  beforeEach(() => {
    insert.mockReset().mockResolvedValue({ error: null });
    getDeviceId.mockReset();
  });

  it('drops the event when the account switched while the session was resolving', async () => {
    // Before: the row took device_id from whatever getDeviceId() resolved to,
    // so U1's click was counted as U2's step in the funnel.
    await claimOwner('dev-1');
    let resolveSession: (uid: string) => void = () => {};
    getDeviceId.mockImplementation(() => new Promise<string>((r) => { resolveSession = r; }));

    const pending = track('intent_clicked', { source: 'account' });
    await claimOwner('dev-2');
    resolveSession('dev-2');
    await pending;

    expect(insert).not.toHaveBeenCalled();
  });

  it('a caller that awaited first passes the token it captured at the top of its handler, and that token decides', async () => {
    // Entry capture is inert for such a caller: by the time track() runs the
    // owner has already moved on, and the entry token would name the new
    // account — the gate would compare the new owner against itself.
    await claimOwner('dev-1');
    const owner = captureOwnerToken();
    await claimOwner('dev-2');
    getDeviceId.mockResolvedValue('dev-2');

    await track('ai_feature_used', { feature: 'cold_email' }, owner);

    expect(insert).not.toHaveBeenCalled();
  });

  it('still records the event when the same account resolves', async () => {
    await claimOwner('dev-1');
    getDeviceId.mockResolvedValue('dev-1');
    await track('intent_clicked', { source: 'account' });
    expect(insert).toHaveBeenCalledWith({ device_id: 'dev-1', event: 'intent_clicked', props: { source: 'account' } });
  });

  it('a fresh browser with no identity yet binds its first event to the identity that resolves', async () => {
    // Deliberately looser than the private writers: dropping this would
    // lose every first landing_view, which costs the funnel more than the
    // rare late switch misattributing one event.
    advanceOwnerEpoch(null);
    getDeviceId.mockResolvedValue('dev-1');
    await track('landing_view');
    expect(insert).toHaveBeenCalledWith({ device_id: 'dev-1', event: 'landing_view', props: {} });
  });
});

describe('trackOnce', () => {
  beforeEach(() => {
    insert.mockReset().mockResolvedValue({ error: null });
    getDeviceId.mockReset().mockResolvedValue('dev-1');
    sessionStorage.clear();
  });

  it('fires a given event at most once per tab session', async () => {
    await trackOnce('landing_view');
    await trackOnce('landing_view');
    expect(insert).toHaveBeenCalledTimes(1);
  });

  it('dedupes per event key, not globally', async () => {
    await trackOnce('landing_view');
    await trackOnce('matches_generated');
    expect(insert).toHaveBeenCalledTimes(2);
  });
});
