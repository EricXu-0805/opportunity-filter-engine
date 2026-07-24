import { describe, expect, it } from 'vitest';
import { buildContentSecurityPolicy } from './proxy';

const NONCE = 'a3f9c2e02b414d6c8f0e5a7d9b1c3e5f';

function directives(csp: string): Map<string, string> {
  return new Map(
    csp.split(';').map((d) => {
      const trimmed = d.trim();
      const space = trimmed.indexOf(' ');
      return space === -1 ? [trimmed, ''] : [trimmed.slice(0, space), trimmed.slice(space + 1)];
    }),
  );
}

describe('buildContentSecurityPolicy', () => {
  it('requires the per-request nonce with strict-dynamic for scripts', () => {
    const csp = buildContentSecurityPolicy(NONCE, { isDevelopment: false });
    const scriptSrc = directives(csp).get('script-src');
    expect(scriptSrc).toContain(`'nonce-${NONCE}'`);
    expect(scriptSrc).toContain("'strict-dynamic'");
    expect(scriptSrc).not.toContain("'unsafe-inline'");
    expect(scriptSrc).not.toContain("'unsafe-eval'");
  });

  it('keeps style-src on unsafe-inline with NO nonce (a nonce would disable it and break next/font)', () => {
    const csp = buildContentSecurityPolicy(NONCE, { isDevelopment: false });
    const styleSrc = directives(csp).get('style-src');
    expect(styleSrc).toBe("'self' 'unsafe-inline'");
  });

  it('derives Supabase HTTPS + WSS origins from NEXT_PUBLIC_SUPABASE_URL', () => {
    const csp = buildContentSecurityPolicy(NONCE, {
      isDevelopment: false,
      supabaseUrl: 'https://example-project.supabase.co',
    });
    const connectSrc = directives(csp).get('connect-src');
    expect(connectSrc).toContain('https://example-project.supabase.co');
    expect(connectSrc).toContain('wss://example-project.supabase.co');
  });

  it('includes the backend origin only when NEXT_PUBLIC_API_URL is absolute', () => {
    const absolute = buildContentSecurityPolicy(NONCE, {
      isDevelopment: false,
      apiUrl: 'https://api.example.com/api',
    });
    expect(directives(absolute).get('connect-src')).toContain('https://api.example.com');

    const relative = buildContentSecurityPolicy(NONCE, {
      isDevelopment: false,
      apiUrl: '/api',
    });
    expect(directives(relative).get('connect-src')).toBe("'self'");
  });

  it('omits origins gracefully when env vars are unset', () => {
    const csp = buildContentSecurityPolicy(NONCE, {
      isDevelopment: false,
      supabaseUrl: undefined,
      apiUrl: undefined,
    });
    expect(csp).not.toContain('undefined');
    expect(csp).not.toContain('null');
    expect(directives(csp).get('connect-src')).toBe("'self'");
  });

  it('locks down framing and object embedding', () => {
    const d = directives(buildContentSecurityPolicy(NONCE, { isDevelopment: false }));
    expect(d.get('frame-ancestors')).toBe("'none'");
    expect(d.get('frame-src')).toBe("'none'");
    expect(d.get('object-src')).toBe("'none'");
    expect(d.get('base-uri')).toBe("'self'");
    expect(d.has('upgrade-insecure-requests')).toBe(true);
  });

  it('adds dev-only relaxations without leaking them into production', () => {
    const dev = buildContentSecurityPolicy(NONCE, { isDevelopment: true });
    expect(directives(dev).get('script-src')).toContain("'unsafe-eval'");
    expect(directives(dev).get('connect-src')).toContain('ws://localhost:*');
    expect(directives(dev).has('upgrade-insecure-requests')).toBe(false);

    const prod = buildContentSecurityPolicy(NONCE, { isDevelopment: false });
    expect(prod).not.toContain("'unsafe-eval'");
    expect(prod).not.toContain('ws://localhost');
  });
});
