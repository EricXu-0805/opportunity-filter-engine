import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { webcrypto } from 'node:crypto';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import golden from '../../../tests/fixtures/target-resume-ai-golden.json';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from '@/lib/identity-owner';
import { ApiError } from '@/lib/api';
import type { TargetResumeV1 } from '@/lib/target-resume';
import type { TargetResumeExportFile } from '@/lib/target-resume-export-api';
import TargetResumeExportPanel, { type TargetResumeExportPanelProps } from './TargetResumeExportPanel';
const mocked = vi.hoisted(() => ({ fetch: vi.fn(), download: vi.fn(), locale: 'en' }));
vi.mock('@/i18n/client', () => ({ useLocale: () => mocked.locale }));
vi.mock('@/lib/target-resume-export-api', () => ({ fetchTargetResumeExport: mocked.fetch, downloadTargetResumeExport: mocked.download }));
const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v));
const file = { blob: new Blob(['pdf']), filename: 'resume-en.pdf' };
const deferred = <T,>() => { let resolve!: (v:T) => void; const promise = new Promise<T>(yes => { resolve = yes; }); return { promise, resolve }; };
const props = (): TargetResumeExportPanelProps => ({ draft: clone(golden.draft) as TargetResumeV1, owner: captureOwnerToken()!, contextKey: 'source-one', enabled: true, unsaved: true, outdated: false });
const start = async (name = 'Export PDF') => { fireEvent.click(screen.getByRole('button', { name })); await waitFor(() => expect(mocked.fetch).toHaveBeenCalled()); };
beforeEach(async () => { vi.stubGlobal('crypto', webcrypto); localStorage.clear(); advanceOwnerEpoch('export-owner'); await syncLocalIdentityOwner('export-owner'); mocked.locale = 'en'; mocked.fetch.mockReset().mockResolvedValue(file); mocked.download.mockReset(); });
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });
describe('complete target résumé export', () => {
  it.each(['pdf', 'docx'])('exports the explicit %s click from the unchanged current draft without autosaving', async format => {
    const p = props(); const before = JSON.stringify(p.draft); render(<TargetResumeExportPanel {...p} />);
    expect(screen.getByText(/Includes unsaved edits/)).toBeInTheDocument(); expect(mocked.fetch).not.toHaveBeenCalled();
    await start(format === 'pdf' ? 'Export PDF' : 'Export Word'); await waitFor(() => expect(mocked.download).toHaveBeenCalledWith(file));
    const [payload, options] = mocked.fetch.mock.calls[0]; expect(payload.format).toBe(format); expect(options.owner).toEqual(p.owner);
    expect(payload.projection.sections.length).toBeGreaterThan(0); expect(payload).not.toHaveProperty('draft'); expect(JSON.stringify(p.draft)).toBe(before);
    expect(screen.getByRole('status')).toHaveTextContent('Download started');
  });
  it('changes only export options, retains old-source drafts and includes unsaved manual text', async () => {
    const p = props(); p.outdated = true; p.draft.document.sections[0].blocks[0].lines[0].text = 'Untranslated 王';
    render(<TargetResumeExportPanel {...p} />); expect(screen.getByText(/earlier source materials/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Section headings language' }), { target: { value: 'zh' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Paper size' }), { target: { value: 'a4' } }); await start();
    const projection = mocked.fetch.mock.calls[0][0].projection; expect(projection.locale).toBe('zh'); expect(projection.page_size).toBe('a4'); expect(JSON.stringify(projection)).toContain('Untranslated 王');
  });
  it.each(['text', 'unselected', 'context', 'owner', 'disabled', 'unmount'])('retires a late file on %s change', async change => {
    const held = deferred<TargetResumeExportFile>(); mocked.fetch.mockReturnValue(held.promise); const p = props(); const view = render(<TargetResumeExportPanel {...p} />); await start();
    const signal = mocked.fetch.mock.calls[0][1].signal; const next = { ...p, draft: clone(p.draft) };
    if (change === 'text' || change === 'unselected') { const line = next.draft.document.sections[0].blocks[0].lines[0]; line.text += ' changed'; if (change === 'unselected') line.included = false; }
    if (change === 'context') next.contextKey += '-changed';
    if (change === 'disabled') next.enabled = false;
    if (change === 'owner') await act(async () => { advanceOwnerEpoch('someone-else'); });
    else if (change === 'unmount') view.unmount(); else view.rerender(<TargetResumeExportPanel {...next} />);
    expect(signal.aborted).toBe(true); await act(async () => { held.resolve(file); }); expect(mocked.download).not.toHaveBeenCalled();
  });
  it('cancel ends the operation and allows a new explicit export without reviving the old file', async () => {
    const held = deferred<TargetResumeExportFile>(); mocked.fetch.mockReturnValueOnce(held.promise); render(<TargetResumeExportPanel {...props()} />); await start();
    fireEvent.click(screen.getByRole('button', { name: 'Cancel export' })); expect(mocked.fetch.mock.calls[0][1].signal.aborted).toBe(true);
    await act(async () => { held.resolve(file); }); expect(mocked.download).not.toHaveBeenCalled(); await start(); await waitFor(() => expect(mocked.download).toHaveBeenCalledTimes(1)); expect(mocked.fetch).toHaveBeenCalledTimes(2);
  });
  it('allows only one operation at a time', async () => {
    const held = deferred<TargetResumeExportFile>(); mocked.fetch.mockReturnValueOnce(held.promise); render(<TargetResumeExportPanel {...props()} />); await start();
    expect(screen.getByRole('button', { name: 'Export Word' })).toBeDisabled(); expect(screen.getByRole('combobox', { name: 'Paper size' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Export PDF' })); expect(mocked.fetch).toHaveBeenCalledTimes(1); await act(async () => { held.resolve(file); });
  });
  it('shows only safe failure text and requires explicit retry', async () => {
    mocked.fetch.mockRejectedValueOnce(new ApiError(422, 'unsupported_glyph', 'PRIVATE SERVER TEXT', false)); render(<TargetResumeExportPanel {...props()} />); await start();
    expect(await screen.findByRole('alert')).toHaveTextContent('cannot render'); expect(screen.queryByText('PRIVATE SERVER TEXT')).toBeNull(); expect(mocked.fetch).toHaveBeenCalledTimes(1);
    await start(); await waitFor(() => expect(mocked.download).toHaveBeenCalledTimes(1)); expect(mocked.fetch).toHaveBeenCalledTimes(2);
  });
  it('does not request a file when all sections are deselected', async () => {
    const p=props(); p.draft.document.sections.forEach(s => { s.included=false; }); render(<TargetResumeExportPanel {...p} />); fireEvent.click(screen.getByRole('button', { name: 'Export PDF' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Select at least one'); expect(mocked.fetch).not.toHaveBeenCalled();
  });
  it('localizes the controls and failure without translating draft content', async () => {
    mocked.locale='zh'; mocked.fetch.mockRejectedValueOnce(new ApiError(504, 'export_timeout', 'PRIVATE', false)); render(<TargetResumeExportPanel {...props()} />); await start('导出 PDF'); expect(await screen.findByRole('alert')).toHaveTextContent('导出未及时完成'); expect(mocked.fetch.mock.calls[0][0].projection.locale).toBe('zh');
  });
});


it('retires the pending file when the profile disappears, then exports only the explicit retained draft', async () => {
  const held = deferred<TargetResumeExportFile>(); mocked.fetch.mockReturnValueOnce(held.promise);
  const p = props(); const view = render(<TargetResumeExportPanel {...p} />); await start();
  const snapshot = JSON.stringify(p.draft); const signal = mocked.fetch.mock.calls[0][1].signal;
  view.rerender(<TargetResumeExportPanel {...p} profileAvailable={false} />);
  expect(signal.aborted).toBe(true);
  expect(screen.getByText(/Exports this retained draft without restoring your profile/)).toBeVisible();
  await act(async () => { held.resolve(file); }); expect(mocked.download).not.toHaveBeenCalled();
  expect(screen.getByRole('button', { name: 'Export PDF' })).toBeEnabled();
  await start(); await waitFor(() => expect(mocked.download).toHaveBeenCalledTimes(1));
  expect(mocked.fetch).toHaveBeenCalledTimes(2);
  expect(mocked.fetch.mock.calls[1][0].projection).toEqual(mocked.fetch.mock.calls[0][0].projection);
  expect(JSON.stringify(p.draft)).toBe(snapshot);
});
