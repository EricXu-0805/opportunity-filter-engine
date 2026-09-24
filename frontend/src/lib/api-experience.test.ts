import { createEmptyResumeMaster } from './resume-master';
import { createHash } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { ExperienceEntry, ExperienceUsage, ProfileData } from './types';

vi.mock('./supabase', () => ({
  getRevealAccessToken: async () => null,
  refreshRevealAccessToken: async () => null,
}));
vi.mock('./analytics', () => ({ track: vi.fn() }));
import { generateColdEmail, generateColdEmailStream, getEmailVariants, refineEmail } from './api';

const profile: ProfileData = {
  name: 'Alex', institution: 'UIUC', college: 'Grainger', major: 'CS', grade: 'Sophomore',
  is_international: false, research_interests: 'spectroscopy', skills: [], coursework: ['CS 225'],
};
const fetchMock = vi.fn();
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });
afterEach(() => vi.unstubAllGlobals());
const paths = ['initial', 'stream', 'variants', 'refine'] as const;
type Path = typeof paths[number];
const usage: ExperienceUsage = {
  version: 1, eligible_count: 13, selected: [{ id: 'tail', revision: 4,
    excerpt: 'Built a spectroscopy instrument.', source: { kind: 'manual' } }],
  excluded: [], needs_review: false, notices: [],
};
function response(path: Path) {
  const result = { subject: 'Research inquiry', body: 'Synthetic draft', method: 'ai',
    recipient_status: 'unavailable', variants: [], experience_usage: usage };
  return new Response(path === 'stream' ? `data: ${JSON.stringify({ stage: 'done', ...result })}\n\n`
    : JSON.stringify(result), { status: 200,
    headers: { 'content-type': path === 'stream' ? 'text/event-stream' : 'application/json' } });
}
async function call(path: Path, input: ProfileData) {
  switch (path) {
    case 'initial': return generateColdEmail(input, 'target', { engine: 'ai', resumeBullets: ['Unconfirmed legacy claim'] });
    case 'stream': return generateColdEmailStream(input, 'target', { engine: 'ai', resumeBullets: ['Unconfirmed legacy claim'] });
    case 'variants': return getEmailVariants(input, 'target', ['Unconfirmed legacy claim']);
    case 'refine': return refineEmail('Current draft', 'Make it clearer', input, 'target', { resumeBullets: ['Unconfirmed legacy claim'] });
  }
}

describe('Cold Email confirmed experience envelope', () => {
  it.each(paths)('%s sends the complete library and raw source, without a 12-entry or 500-char cutoff', async (path) => {
    const prefix = '🧪 Earlier source paragraph.\n'.repeat(500);
    const tail = 'Built a spectroscopy instrument.';
    const raw = prefix + tail;
    const entries: ExperienceEntry[] = Array.from({ length: 12 }, (_, i) => ({
      id: `early-${i}`, revision: 1, status: 'confirmed', text: 'Earlier experience. '.repeat(40),
      source: { kind: 'manual' },
    }));
    entries.push({ id: 'tail', revision: 4, status: 'confirmed', text: tail,
      source: { kind: 'resume', signature: createHash('sha256').update(raw).digest('hex'), quote: tail,
        start: Array.from(prefix).length, end: Array.from(raw).length } });
    entries.push({ id: 'not-confirmed', revision: 1, status: 'candidate', text: 'Candidate only', source: { kind: 'manual' } });
    const input = { ...profile, resume_text: raw, experience_entries: entries };
    const original = JSON.stringify(input);
    fetchMock.mockResolvedValueOnce(response(path));
    const result = await call(path, input);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.experience_evidence).toEqual({ version: 1, resume_text: raw, entries });
    expect(sent.experience_evidence.entries[12].source.end).toBe(Array.from(raw).length);
    expect(sent).not.toHaveProperty('resume_bullets');
    expect(sent.profile).not.toHaveProperty('experience_entries');
    expect(result.experience_usage).toEqual(usage);
    expect(JSON.stringify(input)).toBe(original);
  });

  it.each(paths)('%s sends an empty envelope even when a legacy caller provides raw bullets', async (path) => {
    fetchMock.mockResolvedValueOnce(response(path));
    await call(path, profile);
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.experience_evidence).toEqual({ version: 1, resume_text: '', entries: [] });
    expect(sent).not.toHaveProperty('resume_bullets');
  });

  it.each(paths)('%s does not send the full master through existing email requests', async (path) => {
    const input = { ...profile, resume_master: { ...createEmptyResumeMaster('private-master'),
      basics: { links: [], name: { id: 'private-name', revision: 1, status: 'confirmed' as const,
        value: 'MASTER-ONLY-PRIVATE-NAME', source: { kind: 'manual' as const } } } } };
    fetchMock.mockResolvedValueOnce(response(path));
    await call(path, input);
    const body = fetchMock.mock.calls[0][1].body;
    expect(body).not.toContain('resume_master');
    expect(body).not.toContain('MASTER-ONLY-PRIVATE-NAME');
  });

  it('legacy refine with no profile still explicitly declares no experience evidence', async () => {
    fetchMock.mockResolvedValueOnce(response('refine'));
    await refineEmail('Current draft', 'Be concise', undefined, 'target', { resumeBullets: ['Never confirmed'] });
    const sent = JSON.parse(fetchMock.mock.calls[0][1].body);
    expect(sent.profile).toBeNull();
    expect(sent.experience_evidence).toEqual({ version: 1, resume_text: '', entries: [] });
    expect(sent).not.toHaveProperty('resume_bullets');
  });
});
