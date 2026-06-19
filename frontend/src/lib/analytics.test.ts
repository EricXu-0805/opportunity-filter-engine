/* @vitest-environment jsdom */
import { describe, it, expect, beforeEach, vi } from 'vitest';

const insert = vi.fn();
const getDeviceId = vi.fn();

vi.mock('./supabase', () => ({
  supabase: { from: () => ({ insert }) },
  getDeviceId: () => getDeviceId(),
}));

import { track, trackOnce } from './analytics';

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
