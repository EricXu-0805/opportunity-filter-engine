import { createHash } from 'node:crypto';
import { serializeEmailContactContext } from '../src/lib/email-contact-context';
import type { EmailContactContextReceipt } from '../src/lib/types';

/** Only for successful synthetic writing responses. Leaves target/error fixtures untouched. */
export function contactReceiptForRequest(request: unknown): EmailContactContextReceipt {
  const value = request && typeof request === 'object'
    ? (request as Record<string, unknown>).contact_context : undefined;
  const canonical = serializeEmailContactContext(value);
  return { version: 1, purpose: JSON.parse(canonical).purpose,
    context_sig: createHash('sha256').update(canonical, 'utf8').digest('hex') };
}
