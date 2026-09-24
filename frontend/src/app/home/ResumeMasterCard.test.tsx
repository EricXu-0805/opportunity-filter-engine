import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as evidence from '@/lib/experience-evidence';
import { createEmptyResumeMaster, resumeMasterEditBase } from '@/lib/resume-master';
import type { ExperienceEntry, ProfileData, ResumeFact, ResumeMasterV1 } from '@/lib/types';
import { DEFAULT_PROFILE } from './types';
import { ResumeMasterCard } from './ResumeMasterCard';

vi.mock('@/i18n/client', () => ({ useLocale: () => 'en' }));
beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
const fact = (value: string, status: ResumeFact['status'] = 'confirmed'): ResumeFact => ({ id: crypto.randomUUID(), revision: 1, value, status, source: { kind: 'manual' } });
const open = () => { screen.getByText('Open full résumé editor').closest('details')!.open = true; };
const change = (name: string, value: string) => fireEvent.change(screen.getByRole('textbox', { name }), { target: { value } });
const confirm = (name: string) => fireEvent.click(screen.getByRole('button', { name: `Confirm ${name}` }));
const preview = () => within(screen.getByRole('region', { name: 'Résumé preview' }));
const stored = (): ResumeMasterV1 => JSON.parse(screen.getByTestId('master').textContent!);
function Harness({ initial = DEFAULT_PROFILE }: { initial?: ProfileData }) {
  const [profile, setProfile] = useState(initial);
  return <><ResumeMasterCard ready profile={profile} onChange={(master, base) => {
    const current = resumeMasterEditBase(profile);
    if (base.resumeText !== current.resumeText || base.entriesJson !== current.entriesJson || base.masterJson !== current.masterJson) return false;
    setProfile({ ...profile, resume_master: master }); return true;
  }} /><output data-testid="master">{JSON.stringify(profile.resume_master ?? null)}</output></>;
}
describe('complete résumé master editor', () => {
  it('waits for hydration and opens a collapsed editor without inventing profile facts', () => {
    const onChange = vi.fn(() => true);
    const profile = { ...DEFAULT_PROFILE, name: 'Do not infer', university: 'Do not infer a degree' };
    const { rerender } = render(<ResumeMasterCard ready={false} profile={profile} onChange={onChange} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading your profile');
    expect(screen.queryByText('Open full résumé editor')).toBeNull();
    rerender(<ResumeMasterCard ready profile={profile} onChange={onChange} />);
    expect(screen.getByText('Open full résumé editor').closest('details')).not.toHaveAttribute('open');
    open();
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue('');
    expect(preview().getByText('No confirmed content to preview yet.')).toBeVisible();
    expect(screen.getByRole('button', { name: 'Apply changes' })).toBeDisabled();
    expect(screen.getByRole('link', { name: 'View profile save status' })).toHaveAttribute('href', '#profile-save-status');
    expect(onChange).not.toHaveBeenCalled();
  });
  it('keeps candidate input out of the preview until confirmed and excludes it explicitly', () => {
    render(<Harness />); open();
    change('Full name', 'Guoyi Xu');
    expect(preview().queryByText('Guoyi Xu')).toBeNull();
    confirm('Full name');
    expect(preview().getByText('Guoyi Xu')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(stored().basics.name).toMatchObject({ value: 'Guoyi Xu', status: 'confirmed', source: { kind: 'manual' } });
    change('Full name', 'Guoyi Xu (preferred)');
    expect(preview().queryByText('Guoyi Xu (preferred)')).toBeNull();
    confirm('Full name');
    fireEvent.click(screen.getByRole('button', { name: 'Exclude Full name' }));
    expect(preview().queryByText('Guoyi Xu (preferred)')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(stored().basics.name).toMatchObject({ status: 'rejected', value: 'Guoyi Xu (preferred)' });
  });
  it('supports exact contact, education, publication, project, skill and custom fields without parsing dates or authors', () => {
    render(<Harness />); open();
    change('Email', 'research+reply@example.test'); confirm('Email');
    change('Phone', '+86 (021) 0000 ext. 8'); confirm('Phone');
    fireEvent.click(screen.getByRole('button', { name: 'Add education' }));
    change('School', 'Example University'); confirm('School');
    change('Degree', 'B.S., expected'); confirm('Degree');
    change('End date / expected date', 'Spring 20XX (not yet confirmed)'); confirm('End date / expected date');
    fireEvent.click(screen.getByRole('button', { name: 'Add publication' }));
    change('Publication title', 'A Study: α, β, and 中文'); confirm('Publication title');
    change('Authors in exact order', 'A. Xu*, B. Li, and C. Chen'); confirm('Authors in exact order');
    change('Publication status', 'Submitted; not accepted'); confirm('Publication status');
    fireEvent.click(screen.getByRole('button', { name: 'Add experience or project' }));
    change('Role / project title', 'Course project contributor'); confirm('Role / project title');
    fireEvent.click(screen.getByRole('button', { name: 'Add skill' }));
    change('Skill 1', 'Python — introductory coursework only'); confirm('Skill 1');
    fireEvent.click(screen.getByRole('button', { name: 'Add another section' }));
    change('Section heading', 'Awards and service');
    fireEvent.click(screen.getByRole('button', { name: 'Add detail' }));
    change('Additional detail 1', 'Volunteer, no leadership role claimed.'); confirm('Additional detail 1');
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(stored().education[0].end?.value).toBe('Spring 20XX (not yet confirmed)');
    expect(stored().publications[0].authors?.value).toBe('A. Xu*, B. Li, and C. Chen');
    expect(stored().publications[0].publication_status?.value).toBe('Submitted; not accepted');
    expect(preview().getByText('Python — introductory coursework only')).toBeVisible();
    expect(stored().section_order).toContain(stored().other_sections[0].id);
  });
  it('keeps long content and complete original source intact, including the tail', async () => {
    const raw = `姓名与经历 ${'完整限定条件。'.repeat(1_000)} END OF SOURCE`;
    const signature = await evidence.sourceDigest(raw);
    const master = createEmptyResumeMaster();
    master.basics.name = { ...fact(raw, 'candidate'), source: { kind: 'resume', signature, quote: raw, start: 0, end: Array.from(raw).length } };
    render(<Harness initial={{ ...DEFAULT_PROFILE, resume_text: raw, resume_master: master }} />); open();
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue(raw);
    const source = screen.getByText('View original source').closest('details')!; source.open = true;
    expect(within(source).getByText(raw)).toHaveTextContent('END OF SOURCE');
    const currentSource = screen.getByText('View complete current résumé source').closest('details')!; currentSource.open = true;
    expect(within(currentSource).getByText(raw)).toHaveTextContent('END OF SOURCE');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Confirm Full name' })).not.toBeDisabled());
    confirm('Full name');
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(stored().basics.name?.value).toBe(raw);
    expect(stored().basics.name?.source).toMatchObject({ quote: raw, signature });
    expect(preview().getByText(raw)).toBeVisible();
  });
  it('references only active confirmed experience versions and never puts candidates or stale refs in preview', async () => {
    const raw = 'Current exact source.';
    const signature = await evidence.sourceDigest(raw);
    const entries: ExperienceEntry[] = [
      { id: 'active', revision: 2, status: 'confirmed', text: 'Confirmed manual detail.', source: { kind: 'manual' } },
      { id: 'candidate', revision: 1, status: 'candidate', text: 'Unconfirmed detail.', source: { kind: 'manual' } },
      { id: 'old-source', revision: 1, status: 'confirmed', text: 'Old source detail.', source: { kind: 'resume', signature: 'f'.repeat(64), quote: raw, start: 0, end: raw.length } },
      { id: 'current-source', revision: 1, status: 'confirmed', text: 'Verified source detail.', source: { kind: 'resume', signature, quote: raw, start: 0, end: raw.length } },
    ];
    const master = createEmptyResumeMaster(); master.activities.push({ id: 'project', kind: 'project', details: [{ id: 'active', revision: 1 }] });
    render(<Harness initial={{ ...DEFAULT_PROFILE, resume_text: raw, experience_entries: entries, resume_master: master }} />); open();
    expect(screen.queryByRole('checkbox', { name: 'Unconfirmed detail.' })).toBeNull();
    expect(screen.queryByRole('checkbox', { name: 'Old source detail.' })).toBeNull();
    expect(preview().queryByText('Confirmed manual detail.')).toBeNull();
    fireEvent.click(screen.getByRole('checkbox', { name: 'Confirmed manual detail.' }));
    await waitFor(() => expect(screen.getByRole('checkbox', { name: 'Verified source detail.' })).toBeEnabled());
    fireEvent.click(screen.getByRole('checkbox', { name: 'Verified source detail.' }));
    expect(preview().getByText('Confirmed manual detail.')).toBeVisible();
    expect(preview().getByText('Verified source detail.')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(stored().activities[0].details).toEqual([{ id: 'active', revision: 2 }, { id: 'current-source', revision: 1 }]);
  });
  it.each(['source', 'entries', 'master'] as const)('preserves an unsaved buffer when the external %s changes and blocks stale apply', (kind) => {
    const onChange = vi.fn(() => true);
    const master = createEmptyResumeMaster(); master.basics.name = fact('Original name');
    const profile: ProfileData = { ...DEFAULT_PROFILE, resume_text: 'original raw', resume_master: master };
    const { rerender } = render(<ResumeMasterCard ready profile={profile} onChange={onChange} />); open();
    change('Full name', 'My unsaved correction');
    const newer = { ...profile };
    if (kind === 'source') newer.resume_text = 'new raw';
    if (kind === 'entries') newer.experience_entries = [{ id: 'new', revision: 1, status: 'candidate', text: 'New candidate', source: { kind: 'manual' } }];
    if (kind === 'master') newer.resume_master = { ...master, revision: 2, basics: { links: [], name: fact('Other saved name') } };
    rerender(<ResumeMasterCard ready profile={newer} onChange={onChange} />);
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue('My unsaved correction');
    expect(screen.getByRole('alert')).toHaveTextContent('unsaved edits are still here');
    expect(screen.getByRole('button', { name: 'Apply changes' })).toBeDisabled();
    expect(onChange).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Discard unsaved edits and load current version' }));
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue(kind === 'master' ? 'Other saved name' : 'Original name');
  });
  it('passes the full loaded bundle on apply and retains edits when the parent rejects it', () => {
    const onChange = vi.fn(() => false);
    const master = createEmptyResumeMaster();
    const profile: ProfileData = { ...DEFAULT_PROFILE, resume_text: 'raw', experience_entries: [], resume_master: master };
    render(<ResumeMasterCard ready profile={profile} onChange={onChange} />); open();
    change('Full name', 'Local edit'); confirm('Full name');
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ revision: 2 }), resumeMasterEditBase(profile));
    expect(screen.getByRole('alert')).toHaveTextContent('were not accepted');
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue('Local edit');
  });
  it('keeps over-limit input intact and reports a blocked preview/apply instead of truncating it', () => {
    const onChange = vi.fn(() => true);
    render(<ResumeMasterCard ready profile={DEFAULT_PROFILE} onChange={onChange} />); open();
    const long = 'x'.repeat(60_001);
    change('Full name', long);
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue(long);
    expect(preview().getByRole('status')).toHaveTextContent('size limits');
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(screen.getByRole('alert')).toHaveTextContent('full input is preserved');
    expect(onChange).not.toHaveBeenCalled();
  });
  it('does not overwrite malformed stored data or use a stale digest to confirm a source', async () => {
    let resolve!: (value: string) => void;
    vi.spyOn(evidence, 'sourceDigest').mockImplementationOnce(() => new Promise((done) => { resolve = done; }));
    const master = createEmptyResumeMaster();
    master.basics.name = { ...fact('Old source', 'candidate'), source: { kind: 'resume', signature: 'a'.repeat(64), quote: 'Old source', start: 0, end: 10 } };
    const onChange = vi.fn(() => true);
    const { rerender } = render(<ResumeMasterCard ready profile={{ ...DEFAULT_PROFILE, resume_text: 'Old source', resume_master: master }} onChange={onChange} />); open();
    rerender(<ResumeMasterCard ready profile={{ ...DEFAULT_PROFILE, resume_text: 'New source', resume_master: master }} onChange={onChange} />);
    await act(async () => resolve('a'.repeat(64)));
    expect(screen.getByRole('button', { name: 'Confirm Full name' })).toBeDisabled();
    expect(preview().queryByText('Old source')).toBeNull();
    rerender(<ResumeMasterCard ready profile={{ ...DEFAULT_PROFILE, resume_master: { wrong: 'shape' } as unknown as ResumeMasterV1 }} onChange={onChange} />);
    expect(screen.getByRole('alert')).toHaveTextContent('has not been replaced');
    expect(screen.queryByText('Open full résumé editor')).toBeNull(); expect(onChange).not.toHaveBeenCalled();
  });
  it('retains required empty link, skill and custom drafts without crashing or replacing confirmed content', () => {
    const master = createEmptyResumeMaster(); master.basics.name = fact('Keep this name');
    render(<Harness initial={{ ...DEFAULT_PROFILE, resume_master: master }} />); open();
    fireEvent.click(screen.getByRole('button', { name: 'Add link' }));
    expect(preview().getByRole('status')).toHaveTextContent('empty added fields');
    change('Link label', 'Personal research site');
    change('Link URL', 'https://example.test/research'); confirm('Link URL');
    expect(preview().getByText('Personal research site')).toBeVisible();
    expect(preview().getByText('https://example.test/research')).toBeVisible();
    change('Link URL', '');
    expect(screen.getByRole('textbox', { name: 'Link URL' })).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(screen.getByRole('alert')).toHaveTextContent('full input is preserved');
    expect(stored().basics.name?.value).toBe('Keep this name');
    fireEvent.click(screen.getByRole('button', { name: 'Remove link' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add skill' }));
    expect(preview().getByRole('status')).toHaveTextContent('empty added fields');
    change('Skill 1', 'Basic R'); confirm('Skill 1'); change('Skill 1', '');
    expect(preview().getByRole('status')).toHaveTextContent('empty added fields');
    fireEvent.click(screen.getByRole('button', { name: 'Remove skill' }));
    fireEvent.click(screen.getByRole('button', { name: 'Add another section' }));
    expect(preview().getByRole('status')).toHaveTextContent('empty added fields');
    change('Section heading', 'Service');
    fireEvent.click(screen.getByRole('button', { name: 'Add detail' }));
    expect(preview().getByRole('status')).toHaveTextContent('empty added fields');
    change('Additional detail 1', 'Library volunteer'); confirm('Additional detail 1');
    expect(preview().getByText('Library volunteer')).toBeVisible();
    change('Additional detail 1', '');
    expect(preview().getByRole('status')).toHaveTextContent('empty added fields');
    fireEvent.click(screen.getByRole('button', { name: 'Remove section' }));
    expect(preview().getByText('Keep this name')).toBeVisible();
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(stored().basics.name?.value).toBe('Keep this name');
    expect(stored().basics.links).toEqual([]); expect(stored().skills).toEqual([]); expect(stored().other_sections).toEqual([]);
  });
  it('keeps a buffer across equal profile replacements and a temporary hydration pause', () => {
    const onChange = vi.fn(() => true);
    const profile = { ...DEFAULT_PROFILE, resume_master: createEmptyResumeMaster() };
    const { rerender } = render(<ResumeMasterCard ready profile={profile} onChange={onChange} />); open();
    change('Full name', 'Unapplied name');
    rerender(<ResumeMasterCard ready profile={JSON.parse(JSON.stringify(profile))} onChange={onChange} />);
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue('Unapplied name');
    expect(screen.queryByRole('alert')).toBeNull();
    rerender(<ResumeMasterCard ready={false} profile={profile} onChange={onChange} />);
    expect(screen.queryByText('Open full résumé editor')).toBeNull();
    rerender(<ResumeMasterCard ready profile={profile} onChange={onChange} />); open();
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue('Unapplied name');
    expect(onChange).not.toHaveBeenCalled();
  });
  it('does not treat recursively reordered JSON object keys as a new source or master revision', () => {
    const master = createEmptyResumeMaster(); master.basics.name = fact('Saved name');
    const profile: ProfileData = { ...DEFAULT_PROFILE, resume_text: 'source text', resume_master: master,
      experience_entries: [{ id: 'entry', revision: 2, status: 'confirmed', text: 'Kept detail', source: { kind: 'manual' } }] };
    const onChange = vi.fn(() => true);
    const { rerender } = render(<ResumeMasterCard ready profile={profile} onChange={onChange} />); open();
    change('Full name', 'Still editing');
    const reverseKeys = (value: unknown): unknown => Array.isArray(value) ? value.map(reverseKeys)
      : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).reverse().map(([key, item]) => [key, reverseKeys(item)])) : value;
    const reordered = reverseKeys(profile) as ProfileData;
    expect(JSON.stringify(reordered.resume_master)).not.toBe(JSON.stringify(profile.resume_master));
    rerender(<ResumeMasterCard ready profile={reordered} onChange={onChange} />);
    expect(screen.getByRole('textbox', { name: 'Full name' })).toHaveValue('Still editing');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.getByRole('button', { name: 'Apply changes' })).toBeEnabled();
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ basics: expect.objectContaining({ name: expect.objectContaining({ value: 'Still editing' }) }) }), resumeMasterEditBase(profile));
  });
  it('clears optional facts and reorders sections without writing unsupported empty fields', () => {
    const master = createEmptyResumeMaster(); master.basics.name = fact('Remove me');
    render(<Harness initial={{ ...DEFAULT_PROFILE, resume_master: master }} />); open();
    change('Full name', '');
    fireEvent.click(screen.getByRole('button', { name: 'Move up Education' }));
    fireEvent.click(screen.getByRole('button', { name: 'Apply changes' }));
    expect(stored().basics).not.toHaveProperty('name');
    expect(stored().section_order.slice(0, 2)).toEqual(['education', 'basics']);
  });
});
