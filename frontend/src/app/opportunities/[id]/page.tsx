import type { Metadata } from 'next';
import { notFound } from 'next/navigation';
import { fetchOpportunityServer, fetchSimilarServer } from '@/lib/api-server';
import OpportunityDetail from './OpportunityDetail';

interface PageProps {
  params: { id: string };
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const opp = await fetchOpportunityServer(params.id);
  if (!opp) {
    return { title: 'Opportunity not found — OpportunityEngine' };
  }

  const org = opp.organization ? ` at ${opp.organization}` : '';
  const title = `${opp.title}${org}`;
  const description = (opp.description_clean || opp.description_raw || '').slice(0, 160);
  const keywords = opp.keywords?.slice(0, 10) ?? [];

  const ogImage = `/api/og/opportunity/${encodeURIComponent(opp.id)}`;

  return {
    title: `${title} — OpportunityEngine`,
    description: description || `${opp.opportunity_type} opportunity at ${opp.organization ?? 'UIUC'}.`,
    keywords: keywords.length > 0 ? keywords : undefined,
    openGraph: {
      title,
      description: description || undefined,
      type: 'article',
      siteName: 'OpportunityEngine',
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
  const [opp, similar] = await Promise.all([
    fetchOpportunityServer(params.id),
    fetchSimilarServer(params.id, 5),
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
      name: opp.organization ?? 'University of Illinois Urbana-Champaign',
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
        dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
      />
      <OpportunityDetail opp={opp} similar={similar} />
    </>
  );
}
