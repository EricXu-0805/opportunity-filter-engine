'use client';

import { useState } from 'react';
import { useWritingTarget } from '@/lib/use-writing-target';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { ProfileRefreshState } from '@/lib/use-profile-refresh';
import FullTargetResumeModal from './FullTargetResumeModal';
import ResumeRenovationModal from './ResumeRenovationModal';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  onCloseRequestChange?: (request: (() => boolean) | null) => void;
  profile: ProfileData;
  opportunity: Opportunity;
  targetReady?: boolean;
  targetChecking?: boolean;
  profileAvailable?: boolean;
  profileRefresh?: ProfileRefreshState;
}

function WorkspaceSession({ onClose, onCloseRequestChange, profile, opportunity: initialTarget, targetReady: membership = true, targetChecking: parentChecking = false, profileAvailable, profileRefresh }: Omit<Props, 'isOpen'>) {
  const [mode, setMode] = useState<'full' | 'bullets'>('full');
  const targetRefresh = useWritingTarget(true, initialTarget.id);
  const opportunity = targetRefresh.target ?? initialTarget;
  const targetReady = membership && targetRefresh.status === 'ready';
  const targetChecking = parentChecking || targetRefresh.status === 'checking';
  return mode === 'full'
    ? <FullTargetResumeModal isOpen onClose={onClose} profile={profile}
        opportunity={opportunity} targetReady={targetReady} targetChecking={targetChecking} targetRefresh={targetRefresh} targetMembershipReady={membership} profileAvailable={profileAvailable} profileRefresh={profileRefresh} onCloseRequestChange={onCloseRequestChange} onOpenLegacy={() => setMode('bullets')} />
    : <ResumeRenovationModal isOpen onClose={onClose} profile={profile}
        opportunityId={opportunity.id} opportunityTitle={opportunity.title} targetReady={targetReady} targetChecking={targetChecking} targetRefresh={targetRefresh} targetMembershipReady={membership} target={opportunity} targetKey={JSON.stringify(opportunity)} profileAvailable={profileAvailable} profileRefresh={profileRefresh} onCloseRequestChange={onCloseRequestChange}
        onOpenFull={() => setMode('full')} />;
}

/** Reopening or changing target starts a fresh owner-guarded modal session. */
export default function ResumeWorkspaceModal({ isOpen, ...props }: Props) {
  return isOpen ? <WorkspaceSession key={props.opportunity.id} {...props} /> : null;
}
