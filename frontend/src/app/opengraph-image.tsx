import { ImageResponse } from 'next/og';

export const alt = 'JoinALab — evidence-based research & internship matching';
export const size = { width: 1200, height: 630 };
export const contentType = 'image/png';

export default async function OGImage() {
  return new ImageResponse(
    (
      <div
        style={{
          width: '100%',
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          padding: '80px',
          background: 'linear-gradient(135deg, #0f172a 0%, #1e3a8a 50%, #5b21b6 100%)',
          color: 'white',
          fontFamily: 'system-ui, -apple-system, sans-serif',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 24,
            marginBottom: 48,
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 96,
              height: 96,
              borderRadius: 24,
              background: 'linear-gradient(135deg, #818cf8 0%, #a78bfa 100%)',
              fontSize: 64,
              fontWeight: 900,
              letterSpacing: '-3px',
              color: 'white',
            }}
          >
            J
          </div>
          <span style={{ fontSize: 44, fontWeight: 700, letterSpacing: '-1.5px' }}>
            JoinALab
          </span>
        </div>

        <h1
          style={{
            display: 'flex',
            flexDirection: 'column',
            fontSize: 76,
            fontWeight: 800,
            letterSpacing: '-2.5px',
            lineHeight: 1.1,
            margin: 0,
            marginBottom: 24,
            maxWidth: 1000,
          }}
        >
          <span>Find research & internships</span>
          <span style={{ display: 'flex', gap: 16 }}>
            <span>that</span>
            <span style={{ color: '#a5b4fc' }}>actually match</span>
            <span>you.</span>
          </span>
        </h1>

        <p
          style={{
            fontSize: 26,
            fontWeight: 400,
            color: 'rgba(255,255,255,0.75)',
            margin: 0,
            maxWidth: 1000,
            lineHeight: 1.4,
          }}
        >
          Evidence-based matching for research & internships · built by students, for students
        </p>

        <div
          style={{
            marginTop: 'auto',
            display: 'flex',
            gap: 16,
            fontSize: 18,
            color: 'rgba(255,255,255,0.6)',
          }}
        >
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#a5b4fc" strokeWidth="2">
              <circle cx="12" cy="12" r="9" />
              <circle cx="12" cy="12" r="5" />
              <circle cx="12" cy="12" r="1" fill="#a5b4fc" stroke="none" />
            </svg>
            thousands of opportunities
          </span>
          <span>·</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#86efac" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="m5 12 4 4L19 6" />
            </svg>
            Deterministic match
          </span>
          <span>·</span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="#fbbf24">
              <path d="M13 2 4 14h7l-1 8 10-13h-7l1-7Z" />
            </svg>
            Free · Privacy-first
          </span>
        </div>
      </div>
    ),
    size,
  );
}
