import { fireEvent, render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { dictionaries } from '@/i18n/dictionaries';
import type { PrivateImportListView } from '@/lib/use-private-import-list';
import type { PrivateImportTarget } from '@/lib/private-import-target-api';
const feed = vi.hoisted(() => ({ locale: 'en' as 'en' | 'zh', state: null as unknown as PrivateImportListView, refresh: vi.fn(), more: vi.fn(), open: vi.fn(), close: vi.fn(), remove: vi.fn(), signIn: vi.fn() }));
vi.mock('@/lib/use-private-import-list', () => ({ usePrivateImportList: () => ({ state: feed.state, refresh: feed.refresh, loadMore: feed.more, open: feed.open, close: feed.close, remove: feed.remove }) }));
vi.mock('@/lib/auth-modal-context', () => ({ useAuthModal: () => ({ openModal: feed.signIn }) }));
vi.mock('@/i18n/client', () => ({ useT: () => ({ locale: feed.locale, t: translate }) }));
import PrivateImportList from './PrivateImportList';
function translate(key: string): string { return String(key.split('.').reduce<unknown>((value, part) => (value as Record<string, unknown>)[part], dictionaries[feed.locale])); }
function target(revision = 2): PrivateImportTarget { return { id: 'private-import:aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', owner_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', revision, created_at: '2026-09-28T12:00:00Z', updated_at: '2026-09-28T12:00:00Z', deleted_at: null, target_scope: 'private_import', verification: 'unverified', target_version: `pit1:${revision}`,
 opportunity: { source: 'url_parser', source_url: 'https://example.edu/source', url: 'https://example.edu/source', title: 'Full cloud source', description_raw: 'Source body. '.repeat(500) + 'FINAL CLOUD RESTRICTION', extra_fields: { description_source: 'page_text', ai_input_scope: 'full_source', suggested_skills: ['Python'] } }, import_source: { version: 1, description_source: 'page_text', ai_input_scope: 'source_excerpt', llm_enriched: true } }; }
function ready(): PrivateImportListView { return { status: 'ready', items: [{ id: target().id, owner_id: target().owner_id, revision: 2, created_at: target().created_at, updated_at: target().updated_at, deleted_at: null, target_scope: 'private_import', verification: 'unverified', target_version: target().target_version, title: 'Cloud summary', organization: 'Source institution', source_url: '', url: '', source: 'url_parser' }], cursor: null, code: null, more: 'idle', detail: { status: 'closed' }, deleted: false }; }
beforeEach(() => { feed.locale = 'en'; feed.state = ready(); for (const fn of [feed.refresh, feed.more, feed.open, feed.close, feed.remove, feed.signIn]) fn.mockReset(); });
describe('account import list display', () => {
  it.each(['en', 'zh'] as const)('%s distinguishes loading, failed read, signed out and real empty', locale => {
    feed.locale = locale; feed.state = { ...ready(), status: 'loading', items: [] }; const view = render(<PrivateImportList />);
    expect(screen.getByText(translate('privateImport.loading'))).toBeInTheDocument(); expect(screen.queryByText(translate('privateImport.empty'))).toBeNull();
    feed.state = { ...feed.state, status: 'error', code: 'unavailable' }; view.rerender(<PrivateImportList />);
    expect(screen.getByRole('alert')).toHaveTextContent(translate('privateImport.unavailable')); expect(screen.queryByText(translate('privateImport.empty'))).toBeNull();
    fireEvent.click(screen.getByText(translate('privateImport.refresh'))); expect(feed.refresh).toHaveBeenCalledOnce();
    feed.state = { ...feed.state, status: 'sign_in_required' }; view.rerender(<PrivateImportList />);
    fireEvent.click(screen.getByText(translate('privateImport.signIn'))); expect(feed.signIn).toHaveBeenCalledWith({ phase: 'signin' });
    feed.state = { ...feed.state, status: 'ready', code: null }; view.rerender(<PrivateImportList />); expect(screen.getByText(translate('privateImport.empty'))).toBeInTheDocument();
  });
  it('keeps loaded summaries on pagination failure and has separate next-page retry', () => {
    feed.state = { ...ready(), cursor: { id: target().id, updated_at: target().updated_at }, more: 'error', code: 'timeout' }; render(<PrivateImportList />);
    expect(screen.getByText('Cloud summary')).toBeInTheDocument(); expect(screen.queryByText(translate('privateImport.empty'))).toBeNull();
    fireEvent.click(screen.getByText(translate('privateImport.retryMore'))); expect(feed.more).toHaveBeenCalledOnce();
    expect(screen.getByRole('link', { name: translate('applicationRecord.viewRecords') })).toHaveAttribute('href', `/private-imports/${encodeURIComponent(target().id)}`);
  });
  it.each(['en', 'zh'] as const)('%s shows unverified complete source and requires a separate delete confirmation', locale => {
    feed.locale = locale; const current = target(); feed.state = { ...ready(), detail: { status: 'ready', target: current, deleting: false, deleteError: null } };
    render(<PrivateImportList />); const detail = screen.getByRole('region', { name: translate('privateImport.detailTitle') });
    expect(within(detail).getByText(translate('privateImport.unverified'))).toBeInTheDocument();
    expect(within(detail).queryByText(translate('import.fullAiInput'))).toBeNull(); expect(within(detail).getByText(translate('import.excerptAiInput'))).toBeInTheDocument();
    fireEvent.click(within(detail).getByText(translate('import.expandSource'))); expect(within(detail).getByText(/FINAL CLOUD RESTRICTION/)).not.toHaveClass('line-clamp-4');
    expect(within(detail).getByRole('link', { name: translate('privateImport.viewSource') })).toHaveAttribute('href', 'https://example.edu/source');
    fireEvent.click(within(detail).getByText(translate('privateImport.reviewDelete')));
    expect(feed.remove).not.toHaveBeenCalled(); expect(screen.getByText(translate('privateImport.deleteWarning'))).toBeInTheDocument();
    fireEvent.click(screen.getByText(translate('privateImport.confirmDelete'))); expect(feed.remove).toHaveBeenCalledWith(current);
  });
  it('does not reuse delete confirmation after different full detail is loaded', () => {
    const current = target(); feed.state = { ...ready(), detail: { status: 'ready', target: current, deleting: false, deleteError: null } };
    const view = render(<PrivateImportList />); fireEvent.click(screen.getByText(translate('privateImport.reviewDelete')));
    feed.state = { ...feed.state, detail: { status: 'ready', target: target(3), deleting: false, deleteError: null } }; view.rerender(<PrivateImportList />);
    expect(screen.queryByText(translate('privateImport.confirmDelete'))).toBeNull(); expect(feed.remove).not.toHaveBeenCalled();
  });
  it('requires a fresh detail read after delete conflict and disables closing while deleting', () => {
    const current = target(); feed.state = { ...ready(), detail: { status: 'ready', target: current, deleting: false, deleteError: null } };
    const view = render(<PrivateImportList />); fireEvent.click(screen.getByText(translate('privateImport.reviewDelete')));
    feed.state = { ...feed.state, detail: { status: 'ready', target: current, deleting: true, deleteError: null } }; view.rerender(<PrivateImportList />);
    expect(screen.getByText(translate('privateImport.close'))).toBeDisabled(); expect(screen.getByText(translate('privateImport.confirmDelete'))).toBeDisabled();
    feed.state = { ...feed.state, detail: { status: 'ready', target: current, deleting: false, deleteError: 'conflict' } }; view.rerender(<PrivateImportList />);
    expect(screen.queryByText(translate('privateImport.confirmDelete'))).toBeNull(); fireEvent.click(screen.getByText(translate('privateImport.reread'))); expect(feed.open).toHaveBeenCalledWith(current.id);
  });
  it('does not turn an unsafe source string into a clickable link', () => {
    const current = target(); current.opportunity!.source_url = 'javascript:alert(1)'; feed.state = { ...ready(), detail: { status: 'ready', target: current, deleting: false, deleteError: null } };
    render(<PrivateImportList />); expect(screen.queryByRole('link', { name: translate('privateImport.viewSource') })).toBeNull();
  });
});
