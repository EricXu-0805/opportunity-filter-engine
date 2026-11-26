import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const script = readFileSync(resolve(process.cwd(), 'public/sw.js'), 'utf8');

function worker(binding: { uid: string; enabled: boolean } | null, scriptQuery = '?account=1', initialized = true) {
  let onPush!: (event: { data: { json: () => unknown }; waitUntil: (work: Promise<void>) => void }) => void;
  const showNotification = vi.fn();
  runInNewContext(script, {
    self: {
      location: { search: scriptQuery },
      addEventListener: (name: string, listener: typeof onPush) => { if (name === 'push') onPush = listener; },
      registration: { showNotification },
    },
    navigator: { locks: { request: (name: string, run: () => Promise<void>) => {
      expect(name).toBe('ofe-push-binding'); return run();
    } } },
    caches: { has: async () => initialized, open: async (name: string) => {
      expect(name).toBe('ofe-push-binding-v1');
      return { match: async (key: string) => {
        expect(key).toBe('/.ofe/push-owner');
        return binding && { json: async () => binding };
      } };
    } },
  });
  return {
    showNotification,
    send: (recipient?: string) => new Promise<void>((resolveDelivery, reject) => {
      onPush({ data: { json: () => ({ recipient, title: 'Follow up', url: '/tracker' }) },
        waitUntil: task => { task.then(resolveDelivery, reject); } });
    }),
  };
}

describe('closed-browser reminder delivery', () => {
  it('preserves an untouched legacy subscription when the worker updates before the user revisits', async () => {
    const untouched = worker(null, '', false);
    await untouched.send('A');
    expect(untouched.showNotification).toHaveBeenCalledOnce();
    const migrating = worker(null, '', true);
    await migrating.send('A');
    expect(migrating.showNotification).not.toHaveBeenCalled();
  });

  it('drops a queued A or pre-upgrade message and shows the current B reminder', async () => {
    const client = worker({ uid: 'B', enabled: true });
    await client.send('A');
    await client.send();
    expect(client.showNotification).not.toHaveBeenCalled();
    await client.send('B');
    expect(client.showNotification).toHaveBeenCalledExactlyOnceWith('Follow up', expect.objectContaining({ data: { url: '/tracker' } }));
  });

  it.each([null, { uid: 'A', enabled: false }])('holds delivery without an enabled binding', async binding => {
    const client = worker(binding);
    await client.send('A');
    expect(client.showNotification).not.toHaveBeenCalled();
  });
});
