'use client';

import type { ComponentProps } from 'react';
import { useWritingTarget } from '@/lib/use-writing-target';
import ColdEmailModal from './ColdEmailModal';

/** Real entry: a full detail receipt grants writing authority, never list membership. */
export default function CheckedColdEmailModal(props: ComponentProps<typeof ColdEmailModal>) {
  const refresh = useWritingTarget(props.isOpen, props.opportunityId);
  const target = refresh.target ?? props.target ?? null;
  const membership = props.targetReady ?? true;
  return <ColdEmailModal {...props} target={target} targetRefresh={refresh}
    opportunityTitle={target?.title ?? props.opportunityTitle}
    opportunitySchool={target?.school ?? props.opportunitySchool}
    reminderTarget={target ?? props.reminderTarget}
    targetMembershipReady={membership}
    targetReady={membership && refresh.status === 'ready'}
    targetChecking={!!props.targetChecking || refresh.status === 'checking'} />;
}
