import { beforeEach, expect, it, vi } from 'vitest';
const read = vi.hoisted(() => vi.fn());
vi.mock('./api', () => ({ getOpportunityById: read }));
import { verifyComposeRecipient } from './email-compose';
import { emailTarget, EMAIL_TARGET_VERSION } from '@/components/ColdEmailModal.test-fixtures';
const current = { ...emailTarget('lab'), contact_email_status: 'revealed', contact_email: 'lab@example.edu' };
beforeEach(() => read.mockReset().mockResolvedValue(current));
it('accepts only current full detail, version and exact revealed recipient', async () => {
  const signal = new AbortController().signal;
  await verifyComposeRecipient('lab', EMAIL_TARGET_VERSION, 'lab@example.edu', signal);
  expect(read).toHaveBeenCalledWith('lab', { signal });
});
it.each([{ contact_email_status: 'unavailable' }, { contact_email_status: 'sign_in_required' }, { contact_email: 'changed@example.edu' }])('refuses revoked or changed recipient %j', async change => {
  read.mockResolvedValue({ ...current, ...change }); await expect(verifyComposeRecipient('lab', EMAIL_TARGET_VERSION, 'lab@example.edu', new AbortController().signal)).rejects.toThrow('recipient_changed');
});
it.each([{ id: 'other' }, { writing_target_version: `wt1:${'b'.repeat(64)}` }, { application: null }])('refuses changed or malformed detail %j', async change => {
  read.mockResolvedValue({ ...current, ...change }); await expect(verifyComposeRecipient('lab', EMAIL_TARGET_VERSION, 'lab@example.edu', new AbortController().signal)).rejects.toThrow('target_changed');
});
it('does not accept a late response after cancellation', async () => {
  const controller = new AbortController(); controller.abort();
  await expect(verifyComposeRecipient('lab', EMAIL_TARGET_VERSION, 'lab@example.edu', controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
});
