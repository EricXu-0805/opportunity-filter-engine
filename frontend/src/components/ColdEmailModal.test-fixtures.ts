import { createHash, webcrypto } from 'node:crypto';
import { beforeEach, vi } from 'vitest';
import { serializeEmailContactContext } from '@/lib/email-contact-context';
import type { EmailContactContext } from '@/lib/types';
beforeEach(() => { vi.stubGlobal('crypto', webcrypto); });

import type { Opportunity } from '@/lib/types';

export const FIRST_CONTACT_RECEIPT = { version: 1 as const, purpose: 'first_contact' as const,
  context_sig: createHash('sha256').update(serializeEmailContactContext()).digest('hex') };
export const EMAIL_TARGET_VERSION = `wt1:${'a'.repeat(64)}`;
/** A full public target for existing tests that are about editor behavior. */
export function emailTarget(id: string): Opportunity {
  return { id, title: 'Research opportunity', organization: 'UIUC', record_kind: 'listing',
    opportunity_type: 'research', paid: 'unknown', location: 'Urbana', on_campus: true,
    description_clean: 'Research on sensors', keywords: ['sensors'],
    eligibility: { international_friendly: 'unknown', skills_required: [], preferred_year: [], majors: [], citizenship_required: null },
    application: { requires_resume: 'yes', contact_method: 'email', application_effort: 'unknown' },
    metadata: { is_active: true, confidence_score: 1 }, writing_target_version: EMAIL_TARGET_VERSION };
}
/** The service fake supplies successful receipt metadata; explicit bad fields win. */
export async function emailReceipt(result: unknown, id: string, version = EMAIL_TARGET_VERSION, context?: EmailContactContext) {
  const value = await result;
  const contact_context_receipt = { version: 1, purpose: context?.purpose ?? 'first_contact',
    context_sig: createHash('sha256').update(serializeEmailContactContext(context)).digest('hex') };
  if (!value || typeof value !== 'object') return value;
  const receipt = { opportunity_id: id, target_version: version, contact_context_receipt, ...value };
  if ('variants' in receipt && Array.isArray(receipt.variants)) {
    receipt.variants = receipt.variants.map(variant => ({ contact_context_receipt, ...variant }));
  }
  return receipt;
}
