import { ImageResponse } from 'next/og';

export const size = { width: 64, height: 64 };
export const contentType = 'image/png';
export const dynamic = 'force-static';

export default function Icon() {
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
          borderRadius: '14px',
          color: 'white',
          fontSize: 38,
          fontWeight: 800,
          letterSpacing: '-1px',
          fontFamily: 'system-ui, sans-serif',
        }}
      >
        O
      </div>
    ),
    size,
  );
}
