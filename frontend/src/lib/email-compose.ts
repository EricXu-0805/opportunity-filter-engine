import { getOpportunityById } from './api';
import { isPublicDetail } from './public-target-shape';
import { writingTargetVersion } from './writing-target-version';

/** Public writing versions intentionally exclude addresses. Recheck a server-
 * supplied address separately; never replace the student's chosen recipient. */
export async function verifyComposeRecipient(id: string, version: string, recipient: string, signal: AbortSignal): Promise<void> {
  const value = await getOpportunityById(id, { signal });
  if (signal.aborted) throw new DOMException('Cancelled', 'AbortError');
  const publicValue = { ...value }; delete publicValue.contact_email; delete publicValue.contact_email_status;
  if (!isPublicDetail(publicValue, id) || writingTargetVersion(publicValue) !== version) throw new Error('target_changed');
  if (value.contact_email_status !== 'revealed' || typeof value.contact_email !== 'string'
    || value.contact_email.trim() !== recipient) throw new Error('recipient_changed');
}
