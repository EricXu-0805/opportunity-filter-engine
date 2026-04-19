import { ImageResponse } from '@vercel/og';
import { fetchOpportunityServer } from '@/lib/api-server';

export const runtime = 'edge';

const OG_WIDTH = 1200;
const OG_HEIGHT = 630;

function truncate(str: string, max: number): string {
  if (str.length <= max) return str;
  return str.slice(0, max - 1).trimEnd() + '…';
}

function daysUntil(deadline?: string): number | null {
  if (!deadline) return null;
  const dl = Date.parse(deadline + 'T00:00:00Z');
  if (isNaN(dl)) return null;
  return Math.ceil((dl - Date.now()) / 86400000);
}

export async function GET(
  request: Request,
  { params }: { params: { id: string } },
) {
  const opp = await fetchOpportunityServer(params.id);

  if (!opp) {
    return new ImageResponse(
      (
        <div style={notFoundStyle}>
          <div style={{ fontSize: 44, fontWeight: 700 }}>Opportunity not found</div>
          <div style={{ fontSize: 22, color: '#9ca3af', marginTop: 12 }}>OpportunityEngine</div>
        </div>
      ),
      { width: OG_WIDTH, height: OG_HEIGHT },
    );
  }

  const title = truncate(opp.title, 110);
  const org = opp.organization ? truncate(opp.organization, 60) : '';
  const days = daysUntil(opp.deadline);

  const badges: Array<{ label: string; bg: string; fg: string }> = [];
  const typeLabel = (opp.opportunity_type ?? '').replace(/_/g, ' ');
  if (typeLabel) badges.push({ label: capitalize(typeLabel), bg: '#dbeafe', fg: '#1d4ed8' });
  if (opp.paid === 'yes' || opp.paid === 'stipend') {
    badges.push({ label: opp.paid === 'stipend' ? 'Stipend' : 'Paid', bg: '#d1fae5', fg: '#047857' });
  }
  if (opp.on_campus) badges.push({ label: 'On campus', bg: '#f3f4f6', fg: '#4b5563' });
  if ((opp.eligibility as { international_friendly?: string } | undefined)?.international_friendly === 'yes') {
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
              background: 'linear-gradient(135deg, #2563eb 0%, #3b82f6 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'white',
              fontWeight: 800,
              fontSize: 24,
            }}
          >
            OE
          </div>
          <div style={{ display: 'flex', fontSize: 22, fontWeight: 700, color: '#111827' }}>
            Opportunity<span style={{ color: '#2563eb' }}>Engine</span>
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
              {opp.location && <span style={{ color: '#94a3b8' }}>· {opp.location}</span>}
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
          <span>Find research &amp; internships at UIUC</span>
          {opp.deadline && <span>Deadline: {opp.deadline}</span>}
        </div>
      </div>
    ),
    {
      width: OG_WIDTH,
      height: OG_HEIGHT,
      headers: {
        'Cache-Control': 'public, max-age=3600, s-maxage=86400, stale-while-revalidate=604800',
      },
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
