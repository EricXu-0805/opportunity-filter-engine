import { Suspense } from 'react';
import { fetchSimilarServer } from '@/lib/api-server';
import SimilarOpportunitiesContent from './SimilarOpportunitiesContent';

async function Recommendations({ opportunityId }: { opportunityId: string }) {
  const similar = await fetchSimilarServer(opportunityId, 5);
  return <SimilarOpportunitiesContent similar={similar} />;
}

/** Optional content streams into its own slot after the primary detail is ready. */
export default function SimilarOpportunitiesSection({ opportunityId }: { opportunityId: string }) {
  return <Suspense fallback={null}><Recommendations opportunityId={opportunityId} /></Suspense>;
}
