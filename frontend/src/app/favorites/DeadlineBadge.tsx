import { Clock } from 'lucide-react';
import Badge from '@/components/Badge';
import type { TFunc } from './types';

export function DeadlineBadge({
  deadline,
  t,
}: {
  deadline?: string;
  t: TFunc;
}) {
  if (!deadline) return null;
  const dl = new Date(deadline + 'T00:00:00');
  const now = new Date();
  const daysLeft = Math.ceil((dl.getTime() - now.getTime()) / 86400000);
  if (daysLeft < 0) return <Badge variant="red"><Clock className="w-3 h-3" />{t('badges.deadlinePassed')}</Badge>;
  if (daysLeft <= 14) return <Badge variant="orange"><Clock className="w-3 h-3" />{t('badges.dueInDays', { count: daysLeft })}</Badge>;
  return <Badge variant="gray"><Clock className="w-3 h-3" />{deadline}</Badge>;
}
