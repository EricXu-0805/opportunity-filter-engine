import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { fetchOpportunityDetail, fetchSimilarServer } from '@/lib/api-server';
import { PUBLIC_RELEASE_CACHE_VERSION } from '@/lib/release-scope';
import OpportunityDetail from './OpportunityDetail';
import OpportunityUnavailable from './OpportunityUnavailable';
import { buildOpportunityJsonLd } from './json-ld';

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const result = await fetchOpportunityDetail(id);
  if (result.status === 'not-found') {
    return { title: 'Opportunity not found — JoinALab' };
  }
  // An infrastructure failure is not "not found" — a generic title avoids
  // telling search engines / link previews the record doesn't exist.
  if (result.status === 'unavailable') {
    return { title: 'Opportunity — JoinALab' };
  }
  const opp = result.opportunity;

  const org = opp.organization ? ` at ${opp.organization}` : '';
  const title = `${opp.title}${org}`;
  const description = (opp.description_clean || opp.description_raw || '').slice(0, 160);
  const keywords = opp.keywords?.slice(0, 10) ?? [];

  const ogImage = (
    `/api/og/opportunity/${encodeURIComponent(opp.id)}`
    + `?v=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`
  );

  return {
    title: `${title} — JoinALab`,
    description: description || (opp.source_type === 'faculty_research'
      ? `Faculty research profile${opp.organization ? ` at ${opp.organization}` : ''}. Current openings are not confirmed.`
      : `${opp.opportunity_type} opportunity${opp.organization ? ` at ${opp.organization}` : ''}.`),
    keywords: keywords.length > 0 ? keywords : undefined,
    openGraph: {
      title,
      description: description || undefined,
      type: 'article',
      siteName: 'JoinALab',
      publishedTime: opp.source_type === 'faculty_research' ? undefined : opp.posted_date,
      images: [{ url: ogImage, width: 1200, height: 630, alt: title }],
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description: description || undefined,
      images: [ogImage],
    },
    alternates: {
      canonical: `/opportunities/${encodeURIComponent(opp.id)}`,
    },
  };
}

export default async function OpportunityPage({ params }: PageProps) {
  const { id } = await params;
  // Both requests fire concurrently, but the primary detail outcome is what
  // decides notFound()/unavailable() — it must not sit behind the optional
  // "similar opportunities" rail. fetchSimilarServer carries its own bounded
  // timeout and fails open to [], so it only ever adds latency to the ok path.
  const detailPromise = fetchOpportunityDetail(id);
  const similarPromise = fetchSimilarServer(id, 5);
  const result = await detailPromise;
  if (result.status === 'not-found') notFound();
  if (result.status === 'unavailable') return <OpportunityUnavailable />;
  const opp = result.opportunity;
  const similar = await similarPromise;

  const jsonLd = buildOpportunityJsonLd(opp);

  return (
    <>
      {jsonLd && (
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, '\\u003c') }}
        />
      )}
      {/*
        Forces a full remount on every distinct target — client-side
        navigation between two /opportunities/[id] routes would otherwise
        reuse this component instance (React reconciles by position, not by
        route param), leaking Tailor/Renovation modal state and everything
        inside useOpportunityDetail across an opportunity switch.
      */}
      <OpportunityDetail key={opp.id} opp={opp} similar={similar} />
    </>
  );
}
