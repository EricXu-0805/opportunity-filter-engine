import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { fetchOpportunityServer, fetchSimilarServer } from '@/lib/api-server';
import { PUBLIC_RELEASE_CACHE_VERSION } from '@/lib/release-scope';
import OpportunityDetail from './OpportunityDetail';

interface PageProps {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { id } = await params;
  const opp = await fetchOpportunityServer(id);
  if (!opp) {
    return { title: 'Opportunity not found — JoinALab' };
  }

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
    description: description || `${opp.opportunity_type} opportunity${opp.organization ? ` at ${opp.organization}` : ''}.`,
    keywords: keywords.length > 0 ? keywords : undefined,
    openGraph: {
      title,
      description: description || undefined,
      type: 'article',
      siteName: 'JoinALab',
      publishedTime: opp.posted_date,
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
  const [opp, similar] = await Promise.all([
    fetchOpportunityServer(id),
    fetchSimilarServer(id, 5),
  ]);
  if (!opp) notFound();

  const jsonLd = {
    '@context': 'https://schema.org',
    '@type': 'JobPosting',
    title: opp.title,
    description: opp.description_clean || opp.description_raw || '',
    datePosted: opp.posted_date,
    validThrough: opp.deadline,
    employmentType: opp.opportunity_type === 'research' ? 'PART_TIME' : 'INTERN',
    hiringOrganization: {
      '@type': 'Organization',
      name: opp.organization ?? 'Host institution',
    },
    jobLocation: {
      '@type': 'Place',
      address: {
        '@type': 'PostalAddress',
        addressLocality: opp.location,
        addressCountry: 'US',
      },
    },
    baseSalary: opp.paid === 'yes' || opp.paid === 'stipend' ? {
      '@type': 'MonetaryAmount',
      currency: 'USD',
      value: {
        '@type': 'QuantitativeValue',
        value: opp.compensation_details ?? 'See description',
        unitText: 'HOUR',
      },
    } : undefined,
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd).replace(/</g, '\\u003c') }}
      />
      <OpportunityDetail opp={opp} similar={similar} />
    </>
  );
}
