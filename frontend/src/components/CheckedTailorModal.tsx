'use client';

import type { ComponentProps } from 'react';
import { useWritingTarget } from '@/lib/use-writing-target';
import TailorModal from './TailorModal';

export default function CheckedTailorModal(props: ComponentProps<typeof TailorModal>) {
  const refresh = useWritingTarget(props.isOpen, props.opportunityId);
  const target = refresh.target ?? props.target ?? null;
  const membership = props.targetReady ?? true;
  return <TailorModal {...props} target={target} targetRefresh={refresh}
    opportunityTitle={target?.title ?? props.opportunityTitle}
    targetKey={target ? JSON.stringify(target) : props.targetKey}
    targetMembershipReady={membership}
    targetReady={membership && refresh.status === 'ready'}
    targetChecking={!!props.targetChecking || refresh.status === 'checking'} />;
}
