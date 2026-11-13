'use client';

import { getPrivateEmailContext, privateEmailKey, type PrivateEmailContext } from './private-email';
import { PRIVATE_TARGET_READ_DEADLINE_MS, PRIVATE_TARGET_READ_INTERVAL_MS, usePrivateTargetRead,
  type PrivateTargetActionReceipt, type PrivateTargetKind, type PrivateTargetReadState } from './use-private-target-read';

export type PrivateEmailActionReceipt = PrivateTargetActionReceipt<PrivateEmailContext>;
export type PrivateEmailTargetState = PrivateTargetReadState<PrivateEmailContext>;
export const PRIVATE_EMAIL_DEADLINE_MS = PRIVATE_TARGET_READ_DEADLINE_MS;
export const PRIVATE_EMAIL_INTERVAL_MS = PRIVATE_TARGET_READ_INTERVAL_MS;

const EMAIL: PrivateTargetKind<PrivateEmailContext> = {
  read: getPrivateEmailContext,
  key: privateEmailKey,
  id: target => target.id,
  blocked: target => target.contact_policy.state === 'blocked' ? target.contact_policy.reason : null,
};

export function usePrivateEmailTarget(enabled: boolean, opportunityId: string): PrivateEmailTargetState {
  return usePrivateTargetRead(enabled, opportunityId, EMAIL);
}
