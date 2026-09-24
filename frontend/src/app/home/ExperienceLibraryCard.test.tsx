import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { useState } from 'react';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import * as evidence from '@/lib/experience-evidence';
import type { ExperienceEntry, ProfileData } from '@/lib/types';
import { DEFAULT_PROFILE, type TFunc } from './types';
import { ExperienceLibraryCard } from './ExperienceLibraryCard';
const t = ((key: string) => key) as TFunc;
const manual = (): ExperienceEntry => ({ id: 'one', revision: 1, status: 'candidate', text: 'Built a robot.', source: { kind: 'manual' } });
beforeEach(() => vi.stubGlobal('crypto', webcrypto));
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });
function Harness({ initial }: { initial: ProfileData }) {
  const [profile, setProfile] = useState(initial);
  return <><ExperienceLibraryCard profile={profile} ready onChange={(entries, base) => {
    if (base.resumeText !== (profile.resume_text ?? '') || base.entriesJson !== JSON.stringify(profile.experience_entries ?? [])) return false;
    setProfile({ ...profile, experience_entries: entries }); return true;
  }} t={t} /><output data-testid="entries">{JSON.stringify(profile.experience_entries ?? [])}</output></>;
}
const stored = (): ExperienceEntry[] => JSON.parse(screen.getByTestId('entries').textContent!);
const editorFor = (text: string) => { const el = screen.getAllByText(text).find((item) => item.closest('summary'))!.closest('details')!; el.open = true; return el; };
describe('experience library review', () => {
  it('extracts candidates, confirms a correction with original quote and preserves it on re-extraction', async () => {
    render(<Harness initial={{ ...DEFAULT_PROFILE, resume_text: 'Built a Python robot.\n\nMeasured 20 trials.' }} />);
    fireEvent.click(screen.getByRole('button', { name: 'home.experience.extract' }));
    await waitFor(() => expect(stored()).toHaveLength(2));
    expect(stored().every((entry) => entry.status === 'candidate')).toBe(true);
    const editor = editorFor('Built a Python robot.');
    fireEvent.change(within(editor).getByRole('textbox'), { target: { value: 'Built the Python controller for a robot.' } });
    await waitFor(() => expect(within(editor).getByRole('button', { name: 'home.experience.confirmCorrection' })).not.toBeDisabled());
    fireEvent.click(within(editor).getByRole('button', { name: 'home.experience.confirmCorrection' }));
    expect(stored()[0]).toMatchObject({ revision: 2, status: 'confirmed', text: 'Built the Python controller for a robot.', source: { quote: 'Built a Python robot.', start: 0, end: 21 } });
    fireEvent.click(screen.getByRole('button', { name: 'home.experience.extract' }));
    await waitFor(() => expect(screen.queryByRole('button', { name: 'home.experience.extracting' })).toBeNull());
    expect(stored()).toHaveLength(2); expect(stored()[0].revision).toBe(2);
  });
  it('manual additions await confirmation; exclusion and removal are explicit', () => {
    render(<Harness initial={DEFAULT_PROFILE} />);
    const add = editorFor('home.experience.addManual');
    fireEvent.change(within(add).getByRole('textbox'), { target: { value: 'Compared two retrieval methods.' } });
    fireEvent.click(within(add).getByRole('button', { name: 'home.experience.addCandidate' }));
    expect(stored()[0]).toMatchObject({ status: 'candidate', source: { kind: 'manual' } });
    fireEvent.click(within(editorFor('Compared two retrieval methods.')).getByRole('button', { name: 'home.experience.confirm' }));
    expect(stored()[0].status).toBe('confirmed');
    fireEvent.click(within(editorFor('Compared two retrieval methods.')).getByRole('button', { name: 'home.experience.exclude' }));
    expect(stored()[0].status).toBe('rejected');
    fireEvent.click(within(editorFor('Compared two retrieval methods.')).getByRole('button', { name: 'common.remove' }));
    expect(stored()).toEqual([]);
  });
  it('cannot confirm a quote from another resume', async () => {
    const [entry] = await evidence.createResumeCandidates('Old source'); const onChange = vi.fn(() => true);
    render(<ExperienceLibraryCard ready profile={{ ...DEFAULT_PROFILE, resume_text: 'New source', experience_entries: [entry] }} onChange={onChange} t={t} />);
    const button = within(editorFor('Old source')).getByRole('button', { name: 'home.experience.confirm' });
    expect(button).toBeDisabled(); fireEvent.click(button); expect(onChange).not.toHaveBeenCalled();
  });
  it('keeps an over-limit correction for editing without truncating or submitting it', () => {
    const onChange = vi.fn(() => true);
    render(<ExperienceLibraryCard ready profile={{ ...DEFAULT_PROFILE, experience_entries: [manual()] }} onChange={onChange} t={t} />);
    const editor = editorFor('Built a robot.');
    fireEvent.change(within(editor).getByRole('textbox'), { target: { value: 'x'.repeat(6001) } });
    fireEvent.click(within(editor).getByRole('button', { name: 'home.experience.confirmCorrection' }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole('alert').textContent).toBe('home.experience.errors.invalid_entry');
    expect((within(editor).getByRole('textbox') as HTMLTextAreaElement).value).toHaveLength(6001);
  });
  it('reports malformed stored entries instead of replacing them with an empty library', () => {
    const onChange = vi.fn(() => true);
    render(<ExperienceLibraryCard ready profile={{ ...DEFAULT_PROFILE, experience_entries: null } as unknown as ProfileData} onChange={onChange} t={t} />);
    expect(screen.getByRole('alert').textContent).toBe('home.experience.invalidStored');
    expect(screen.queryByRole('button', { name: 'home.experience.extract' })).toBeNull(); expect(onChange).not.toHaveBeenCalled();
  });
  it('carries the original extraction base so newer source changes refuse late results', async () => {
    let settle!: (entries: ExperienceEntry[]) => void;
    vi.spyOn(evidence, 'createResumeCandidates').mockReturnValue(new Promise((resolve) => { settle = resolve; }));
    const onChange = vi.fn(() => false);
    const { rerender } = render(<ExperienceLibraryCard ready profile={{ ...DEFAULT_PROFILE, resume_text: 'before' }} onChange={onChange} t={t} />);
    fireEvent.click(screen.getByRole('button', { name: 'home.experience.extract' }));
    rerender(<ExperienceLibraryCard ready profile={{ ...DEFAULT_PROFILE, resume_text: 'after' }} onChange={onChange} t={t} />);
    await act(async () => settle([manual()]));
    expect(onChange).toHaveBeenCalledWith([manual()], { resumeText: 'before', entriesJson: '[]' });
    expect(screen.getByRole('alert').textContent).toBe('home.experience.errors.stale');
  });
  it('does not write after the account subtree unmounts', async () => {
    let settle!: (entries: ExperienceEntry[]) => void;
    vi.spyOn(evidence, 'createResumeCandidates').mockReturnValue(new Promise((resolve) => { settle = resolve; }));
    const onChange = vi.fn(() => true);
    const { unmount } = render(<ExperienceLibraryCard ready profile={{ ...DEFAULT_PROFILE, resume_text: 'private source' }} onChange={onChange} t={t} />);
    fireEvent.click(screen.getByRole('button', { name: 'home.experience.extract' })); unmount();
    await act(async () => settle([manual()])); expect(onChange).not.toHaveBeenCalled();
  });
});
