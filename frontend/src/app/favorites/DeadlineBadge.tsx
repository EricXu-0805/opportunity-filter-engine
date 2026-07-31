import { Clock } from 'lucide-react';
import Badge from '@/components/Badge';
import type { TFunc } from './types';

export function DeadlineBadge({
  deadline,
  isEstimate,
  t,
}: {
  deadline?: string;
  isEstimate?: boolean;
  t: TFunc;
}) {
  if (!deadline) return null;
  // An estimated date (NSF projected deadlines) must never yield a confident
  // "Deadline passed" / countdown claim — always the neutral gray date with
  // an explicit estimate marker.
  if (isEstimate) return <Badge variant="gray"><Clock className="w-3 h-3" />{`${deadline} · ${t('badges.estimated')}`}</Badge>;
  const dl = new Date(deadline + 'T00:00:00');
  const now = new Date();
  const daysLeft = Math.ceil((dl.getTime() - now.getTime()) / 86400000);
  if (daysLeft < 0) return <Badge variant="red"><Clock className="w-3 h-3" />{t('badges.deadlinePassed')}</Badge>;
  if (daysLeft <= 14) return <Badge variant="orange"><Clock className="w-3 h-3" />{t('badges.dueInDays', { count: daysLeft })}</Badge>;
  return <Badge variant="gray"><Clock className="w-3 h-3" />{deadline}</Badge>;
}
