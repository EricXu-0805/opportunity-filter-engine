import { describe, expect, it } from 'vitest';
import { worker } from './push-worker.test-utils';

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
