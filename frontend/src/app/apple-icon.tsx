import { ImageResponse } from 'next/og';

export const size = { width: 180, height: 180 };
export const contentType = 'image/png';
export const dynamic = 'force-static';

export default function AppleIcon() {
  return new ImageResponse(
    (
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          width: '100%',
          height: '100%',
          background: 'linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)',
          color: 'white',
          fontSize: 112,
          fontWeight: 800,
          letterSpacing: '-3px',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        O
      </div>
    ),
    size,
  );
}
