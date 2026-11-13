'use client';

import { getPrivateResumeContext } from './private-resume';
import { privateResumeKey, type PrivateResumeContext } from './private-resume-context';
import { usePrivateTargetRead, type PrivateTargetActionReceipt, type PrivateTargetKind, type PrivateTargetReadState } from './use-private-target-read';

export type PrivateResumeActionReceipt = PrivateTargetActionReceipt<PrivateResumeContext>;
export type PrivateResumeTargetState = PrivateTargetReadState<PrivateResumeContext>;

const RESUME: PrivateTargetKind<PrivateResumeContext> = {
  read: getPrivateResumeContext,
  key: privateResumeKey,
  id: target => target.opportunity_id,
  reasons: ['too_large'],
};

/** The private résumé editor's bounded, owner-checked read of its source. */
export function usePrivateResumeTarget(enabled: boolean, opportunityId: string): PrivateResumeTargetState {
  return usePrivateTargetRead(enabled, opportunityId, RESUME);
}
