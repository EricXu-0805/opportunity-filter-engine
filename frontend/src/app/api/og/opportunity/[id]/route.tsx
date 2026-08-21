import { ImageResponse } from 'next/og';
import { fetchOpportunityDetail } from '@/lib/api-server';
import { buildOpportunityOgFacts } from './og-facts';

export const runtime = 'edge';

const OG_WIDTH = 1200;
const OG_HEIGHT = 630;

/**
 * The card states terms of an offer — Paid, On campus, "Due in 3d" — and it is
 * an image, so nothing on it can be qualified or clicked through to a caveat.
 * It was served `s-maxage=3600`, which let Vercel's edge keep answering with a
 * card built from an hour-old record: the same URL that a chat app re-fetches
 * would hand back "Paid · Due in 3d" for an hour after the listing closed.
 *
 * Applied to the not-found card too. It had no Cache-Control at all, which is
 * the same bug pointing the other way — a record that appears (a slow backend
 * recovering, a newly published row) stays "Opportunity not found" in every
 * cache that stored the miss.
 *
 * Whatever the chat app that already scraped the URL has stored is beyond
 * reach; this only stops us serving stale terms ourselves.
 */
const NO_STORE = { 'Cache-Control': 'no-store, max-age=0' } as const;

function truncate(str: string, max: number): string {
  if (str.length <= max) return str;
  return str.slice(0, max - 1).trimEnd() + '…';
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  // `fetchOpportunityDetail`, not the legacy record-or-null resolver. That one
  // collapsed a 429, a 5xx, a dropped connection, a timeout and a malformed
  // body into the same answer as a genuinely missing id — so the card told
  // every sharer "Opportunity not found" about a record that exists, and the
  // image was then cached by whatever rendered it. It also echo-checks the id,
  // so a mismatched response can no longer render one record's card under
  // another record's URL.
  const outcome = await fetchOpportunityDetail(id);

  if (outcome.status !== 'ok') {
    // "Not found" is reserved for the backend actually saying so (400/404).
    // Everything else is our side failing, and an image cannot be qualified
    // later — so it says what is true: we could not load it right now.
    const unavailable = outcome.status === 'unavailable';
    return new ImageResponse(
      (
        <div style={notFoundStyle}>
          <div style={{ fontSize: 44, fontWeight: 700 }}>
            {unavailable ? 'Opportunity temporarily unavailable' : 'Opportunity not found'}
          </div>
          {unavailable ? (
            <div style={{ fontSize: 26, color: '#6b7280', marginTop: 10 }}>
              Please try again later
            </div>
          ) : null}
          <div style={{ fontSize: 22, color: '#9ca3af', marginTop: 12 }}>JoinALab</div>
        </div>
      ),
      { width: OG_WIDTH, height: OG_HEIGHT, headers: { ...NO_STORE } },
    );
  }

  const opp = outcome.opportunity;
  const facts = buildOpportunityOgFacts(opp);
  const title = truncate(facts.title, 110);
  const org = facts.organization ? truncate(facts.organization, 60) : '';
  const days = facts.daysUntilDeadline;

  const badges: Array<{ label: string; bg: string; fg: string }> = [];
  if (facts.typeLabel) badges.push({ label: capitalize(facts.typeLabel), bg: '#e0e7ff', fg: '#4338ca' });
  if (facts.showPaid) {
    badges.push({ label: opp.paid === 'stipend' ? 'Stipend' : 'Paid', bg: '#d1fae5', fg: '#047857' });
  }
  if (facts.showOnCampus) badges.push({ label: 'On campus', bg: '#f3f4f6', fg: '#4b5563' });
  if (facts.showInternational) {
    badges.push({ label: 'International OK', bg: '#ede9fe', fg: '#6d28d9' });
  }
  if (days !== null && days >= 0 && days <= 7) {
    badges.push({
      label: `Due in ${days}d`,
      bg: '#fee2e2',
      fg: '#b91c1c',
    });
  } else if (days !== null && days >= 0 && days <= 30) {
    badges.push({ label: `Due in ${days}d`, bg: '#fef3c7', fg: '#b45309' });
  }

  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          padding: '64px 72px',
          background:
            'linear-gradient(135deg, #fafafa 0%, #f0f4ff 60%, #e0e7ff 100%)',
          fontFamily: 'sans-serif',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <div
            style={{
              width: 40,
              height: 40,
              borderRadius: 10,
              background: 'linear-gradient(135deg, #4f46e5 0%, #6366f1 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'white',
              fontWeight: 800,
              fontSize: 24,
            }}
          >
            JL
          </div>
          <div style={{ display: 'flex', fontSize: 22, fontWeight: 700, color: '#111827' }}>
            JoinA<span style={{ color: '#4f46e5' }}>Lab</span>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
          {badges.length > 0 && (
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              {badges.map(b => (
                <div
                  key={b.label}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    padding: '6px 14px',
                    borderRadius: 999,
                    fontSize: 20,
                    fontWeight: 600,
                    background: b.bg,
                    color: b.fg,
                  }}
                >
                  {b.label}
                </div>
              ))}
            </div>
          )}

          <div
            style={{
              fontSize: title.length > 60 ? 52 : 60,
              fontWeight: 800,
              color: '#0f172a',
              lineHeight: 1.1,
              letterSpacing: '-0.02em',
              display: 'flex',
            }}
          >
            {title}
          </div>

          {org && (
            <div
              style={{
                fontSize: 26,
                color: '#475569',
                display: 'flex',
                alignItems: 'center',
                gap: 10,
              }}
            >
              <span>{org}</span>
              {facts.location && (
                <span style={{ color: '#94a3b8' }}>
                  · {facts.locationPrefix ? `${facts.locationPrefix}: ` : ''}{facts.location}
                </span>
              )}
            </div>
          )}
        </div>

        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            borderTop: '1px solid #e2e8f0',
            paddingTop: 24,
            fontSize: 18,
            color: '#64748b',
          }}
        >
          <span>{facts.footer}</span>
          {facts.deadlineLabel && <span>{facts.deadlineLabel}</span>}
        </div>
      </div>
    ),
    {
      width: OG_WIDTH,
      height: OG_HEIGHT,
      headers: { ...NO_STORE },
    },
  );
}

const notFoundStyle = {
  width: '100%',
  height: '100%',
  display: 'flex',
  flexDirection: 'column' as const,
  alignItems: 'center',
  justifyContent: 'center',
  background: '#f9fafb',
  color: '#111827',
  fontFamily: 'sans-serif',
};

function capitalize(s: string): string {
  return s.replace(/\b\w/g, m => m.toUpperCase());
}
