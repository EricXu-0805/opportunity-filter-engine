import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import { expect, vi } from 'vitest';

const script = readFileSync(resolve(process.cwd(), 'public/sw.js'), 'utf8');

export function worker(binding: { uid: string; enabled: boolean } | null, scriptQuery = '?account=1', initialized = true) {
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
