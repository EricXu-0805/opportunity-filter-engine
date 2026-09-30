'use client';

import { useT } from '@/i18n/client';
import type { SimilarOpportunity } from '@/lib/api-server';
import { SimilarOpportunities } from './SimilarOpportunities';

/** Keep translation inside the client boundary; no function crosses the RSC slot. */
export default function SimilarOpportunitiesContent({ similar }: { similar: SimilarOpportunity[] }) {
  const { t } = useT();
  return <SimilarOpportunities similar={similar} t={t} />;
}
