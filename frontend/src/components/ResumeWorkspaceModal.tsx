'use client';

import { useState } from 'react';
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
  profileAvailable?: boolean;
  profileRefresh?: ProfileRefreshState;
}

function WorkspaceSession({ onClose, onCloseRequestChange, profile, opportunity, targetReady, profileAvailable, profileRefresh }: Omit<Props, 'isOpen'>) {
  const [mode, setMode] = useState<'full' | 'bullets'>('full');
  return mode === 'full'
    ? <FullTargetResumeModal isOpen onClose={onClose} profile={profile}
        opportunity={opportunity} targetReady={targetReady} profileAvailable={profileAvailable} profileRefresh={profileRefresh} onCloseRequestChange={onCloseRequestChange} onOpenLegacy={() => setMode('bullets')} />
    : <ResumeRenovationModal isOpen onClose={onClose} profile={profile}
        opportunityId={opportunity.id} opportunityTitle={opportunity.title} targetReady={targetReady} profileAvailable={profileAvailable} profileRefresh={profileRefresh} onCloseRequestChange={onCloseRequestChange}
        onOpenFull={() => setMode('full')} />;
}

/** Reopening or changing target starts a fresh owner-guarded modal session. */
export default function ResumeWorkspaceModal({ isOpen, ...props }: Props) {
  return isOpen ? <WorkspaceSession key={props.opportunity.id} {...props} /> : null;
}
