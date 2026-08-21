import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { fetchOpportunityDetail, fetchSimilarServer } from '@/lib/api-server';
import { PUBLIC_RELEASE_CACHE_VERSION } from '@/lib/release-scope';
import OpportunityDetail from './OpportunityDetail';
import OpportunityUnavailable from './OpportunityUnavailable';
import { buildOpportunityJsonLd } from './json-ld';
import { opportunityRecordKind } from '@/lib/record-kind';
import { targetPosture, targetStatusReason } from '@/lib/target-truth';

interface PageProps {
  params: Promise<{ id: string }>;
}

// Neutral, and specific about which fact the source stated. Not "unavailable"
// for everything: a closed listing, a reference record and a profile that says
// "do not ask" are three different things, and a preview that blurs them tells
// the reader something none of the sources said.
const STATUS_DESCRIPTION = {
  listing_closed: 'This listing is closed and is kept for reference.',
  reference_only: 'Published as reference material, not as an open listing.',
  faculty_not_accepting:
    'This faculty profile states they are not currently accepting undergraduate students.',
  inactive: 'This record is no longer active.',
  record_kind_unverified:
    'Record type is unverified; not presented as an open listing. Check the source.',
  status_unverified: 'Current status could not be confirmed — check the source.',
} as const;

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
  const keywords = opp.keywords?.slice(0, 10) ?? [];

  // Metadata outlives the page: a link preview is cached by the messaging app
  // that rendered it, and a search snippet by the index. So a dead target's
  // scraped copy — "Apply by March 1", "We are recruiting two students" — must
  // not become the description, and its posted_date must not become an
  // article publication date. Both are withheld rather than qualified; a
  // caveat does not survive being pasted into a group chat.
  const posture = targetPosture(opp);
  const reason = targetStatusReason(opp);
  const isOpenListing = posture === 'actionable'
    && opportunityRecordKind(opp) === 'listing';
  // Gated on isOpenListing, NOT on posture alone. An unreviewed source_type
  // with a perfectly valid actionable truth is still a record we have never
  // confirmed is a listing — and its scraped body can say "Apply now" or "we
  // are recruiting two students" just as easily as a real posting's. Faculty
  // profiles are excluded for the same reason: the description is research
  // prose we did not write, and a preview cannot carry the caveat the page
  // does. Both fall through to the neutral text below.
  const description = isOpenListing
    ? (opp.description_clean || opp.description_raw || '').slice(0, 160)
    : '';
  const statusDescription = reason ? STATUS_DESCRIPTION[reason] : '';

  const ogImage = (
    `/api/og/opportunity/${encodeURIComponent(opp.id)}`
    + `?v=${encodeURIComponent(PUBLIC_RELEASE_CACHE_VERSION)}`
  );

  // The fallback when there is no usable description. Opportunity framing
  // ("research opportunity at X") is reserved for a listing we still call
  // open; everything else says what the record is and, when the source told
  // us, why it is not open.
  const fallbackDescription = statusDescription
    ? `${statusDescription}${opp.organization ? ` (${opp.organization})` : ''}`
    : opp.source_type === 'faculty_research'
      ? `Faculty research profile${opp.organization ? ` at ${opp.organization}` : ''}. Current openings are not confirmed.`
      : isOpenListing
        ? `${opp.opportunity_type} opportunity${opp.organization ? ` at ${opp.organization}` : ''}.`
        : `Record${opp.organization ? ` from ${opp.organization}` : ''}. See the source for current details.`;
  const shared = description || fallbackDescription;

  return {
    title: `${title} — JoinALab`,
    description: shared,
    keywords: keywords.length > 0 ? keywords : undefined,
    openGraph: {
      title,
      description: shared,
      type: 'article',
      siteName: 'JoinALab',
      // Only an open listing has a publication date worth asserting. On a
      // closed or unreadable record the date is when we last saw the page,
      // and publishing it as `publishedTime` presents a dead posting as
      // freshly published news.
      publishedTime: isOpenListing ? opp.posted_date : undefined,
      images: [{ url: ogImage, width: 1200, height: 630, alt: title }],
    },
    twitter: {
      card: 'summary_large_image',
      title,
      description: shared,
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
