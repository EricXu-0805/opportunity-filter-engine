import { ImageResponse } from 'next/og';

export const alt = 'OpportunityEngine — AI-powered UIUC research & internship matching';
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
              background: 'linear-gradient(135deg, #60a5fa 0%, #a78bfa 100%)',
              fontSize: 64,
              fontWeight: 900,
              letterSpacing: '-3px',
              color: 'white',
            }}
          >
            O
          </div>
          <span style={{ fontSize: 44, fontWeight: 700, letterSpacing: '-1.5px' }}>
            OpportunityEngine
          </span>
        </div>

        <h1
          style={{
            fontSize: 76,
            fontWeight: 800,
            letterSpacing: '-2.5px',
            lineHeight: 1.1,
            margin: 0,
            marginBottom: 24,
            maxWidth: 1000,
          }}
        >
          Find research & internships that{' '}
          <span
            style={{
              background: 'linear-gradient(90deg, #60a5fa 0%, #a78bfa 100%)',
              backgroundClip: 'text',
              color: 'transparent',
            }}
          >
            actually match
          </span>{' '}
          you.
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
          AI-powered matching for 1,700+ UIUC opportunities · built by students, for students
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
          <span>🎯 1,700+ opportunities</span>
          <span>·</span>
          <span>🤖 AI semantic ranking</span>
          <span>·</span>
          <span>⚡ Free · Privacy-first</span>
        </div>
      </div>
    ),
    size,
  );
}
