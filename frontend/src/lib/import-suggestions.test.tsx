import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { importSuggestions } from './import-suggestions';
import ImportSourceText from '@/components/ImportSourceText';
import { importSourceInfo } from './import-source';
import ImportSuggestions from '@/components/ImportSuggestions';
import { dictionaries } from '@/i18n/dictionaries';
import { customImportToOpp } from '@/app/favorites/types';
import { OpportunityCard } from '@/app/favorites/OpportunityCard';
import { addCustomImport, readCustomImports } from './custom-imports';
import { advanceOwnerEpoch, captureOwnerToken, syncLocalIdentityOwner } from './identity-owner';
import type { ImportedOpportunity } from './api';

afterEach(() => { cleanup(); localStorage.clear(); });

function translate(locale: 'en' | 'zh') {
  return (key: string) => key.split('.').reduce<unknown>((v, k) => (v as Record<string, unknown>)?.[k], dictionaries[locale]) as string;
}

const imported = (extra: Record<string, unknown>): ImportedOpportunity => ({
  source: 'url_parser', source_url: 'https://example.edu/project', url: 'https://example.edu/project',
  title: 'Saved project', description_raw: 'Original source text.', extra_fields: extra,
});

describe('import suggestions stay separate from requirements', () => {
  it.each(['en', 'zh'] as const)('shows new suggestions and the complete summary with %s review wording', (locale) => {
    const t = translate(locale);
    const summary = 'Model summary. ' + 'detail '.repeat(400) + 'LAST SENTENCE.';
    render(<ImportSuggestions skills={['Java', 'R']} summary={summary} t={t} />);
    expect(screen.getByRole('region', { name: t('import.suggestionsTitle') })).toBeInTheDocument();
    expect(screen.getByText(t('import.suggestionsNote'))).toBeInTheDocument();
    expect(screen.getByText('Java')).toBeInTheDocument();
    expect(screen.getByText(/LAST SENTENCE/).textContent).toBe(summary);
    expect(screen.queryByText(t('import.fieldSkillsReq'))).toBeNull();
    expect(screen.queryByText(t('import.fieldSkillsPref'))).toBeNull();
  });

  it('keeps older saved tags as suggestions without changing storage or granting qualifications', async () => {
    advanceOwnerEpoch('b57-import-owner');
    await syncLocalIdentityOwner('b57-import-owner');
    const opportunity = imported({ skills_required: ['Java'], skills_preferred: ['R', 'Java'], needs_manual_review: false });
    const saved = await addCustomImport(opportunity, captureOwnerToken());
    expect(saved.ok).toBe(true);
    if (!saved.ok) throw new Error(saved.reason);
    const before = localStorage.getItem('ofe_custom_imports');
    const restored = readCustomImports()[0];
    const view = customImportToOpp(restored);
    expect(view.eligibility?.skills_required).toBeUndefined();
    expect(view.import_suggestions?.skills).toEqual(['Java', 'R']);
    expect(restored.opportunity).toEqual(opportunity);
    expect(localStorage.getItem('ofe_custom_imports')).toBe(before);
    const t = translate('zh');
    render(<OpportunityCard opp={view} selectionMode={false} isSelected={false} selectedSize={0} isExpanded hasProfile={false}
      onToggleExpand={vi.fn()} onToggleSelect={vi.fn()} onRemove={vi.fn()} onOpenEmailModal={vi.fn()} tailorDisabled={false} t={t} />);
    expect(screen.getByText('Java')).toBeInTheDocument();
    expect(screen.getByText(t('import.suggestionsNote'))).toBeInTheDocument();
    expect(screen.queryByText(t('favorites.requiredSkills'))).toBeNull();
  });

  it('retains all current and legacy suggestions while ignoring malformed display values', () => {
    const extra = { suggested_skills: ['Python', 'R'], skills_required: ['python', 'Java', 7, null], skills_preferred: ['C++'], suggested_description: 'Full summary.' };
    const before = structuredClone(extra);
    expect(importSuggestions(extra)).toEqual({ skills: ['Python', 'R', 'Java', 'C++'], summary: 'Full summary.' });
    expect(extra).toEqual(before);
    expect(importSuggestions({ suggested_skills: 'Python', suggested_description: {} })).toEqual({ skills: [], summary: '' });
  });
});


describe('import source scope and readable tail', () => {
  it.each(['en', 'zh'] as const)('expands and collapses complete original text in %s without treating it as markup', (locale) => {
    const t = translate(locale);
    const text = 'Source paragraph.\n'.repeat(350) + '<script>not executable</script> LAST PARAGRAPH';
    render(<ImportSourceText text={text} info={importSourceInfo({ description_source: 'page_text', ai_input_scope: 'full_source' }, text)} t={t} />);
    const source = screen.getByText(/LAST PARAGRAPH/);
    expect(source.textContent).toBe(text);
    expect(source).toHaveClass('line-clamp-4');
    const expand = screen.getByRole('button', { name: t('import.expandSource') });
    expect(expand).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(expand);
    expect(source).not.toHaveClass('line-clamp-4');
    expect(screen.getByRole('button', { name: t('import.collapseSource') })).toHaveAttribute('aria-expanded', 'true');
    expect(source.querySelector('script')).toBeNull();
    expect(screen.getByText(t('import.fullAiInput'))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: t('import.collapseSource') }));
    expect(source).toHaveClass('line-clamp-4');
    expect(source.textContent).toBe(text);
  });

  it.each([
    [{}, 'source', 'unknown'],
    [{ description_source: 'page_excerpt', ai_input_scope: 'full_source' }, 'source', 'unknown'],
    [{ description_source: 'page_text' }, 'source', 'unknown'],
    [{ description_source: 'page_text', ai_input_scope: ['full_source'] }, 'source', 'unknown'],
    [{ description_source: ['page_text'], ai_input_scope: 'full_source' }, 'source', 'unknown'],
    [{ description_source: 'page_text', ai_input_scope: 'full_source' }, '   ', 'unknown'],
    [{ description_source: 'pasted_text', ai_input_scope: 'full_source' }, 'source', 'full_source'],
    [{ description_source: 'page_text', ai_input_scope: 'source_excerpt' }, 'source', 'source_excerpt'],
    [{ description_source: 'page_excerpt', ai_input_scope: 'source_excerpt' }, 'source', 'source_excerpt'],
  ])('does not promote missing or invalid input scope: %j', (extra, text, expected) => {
    expect(importSourceInfo(extra as Record<string, unknown>, text as string).aiInputScope).toBe(expected);
  });

  it.each(['en', 'zh'] as const)('distinguishes incomplete from unrecorded model input in %s', (locale) => {
    const t = translate(locale);
    const text = 'Full original material';
    const { rerender } = render(<ImportSourceText text={text} info={importSourceInfo({ description_source: 'page_text', ai_input_scope: 'source_excerpt' }, text)} t={t} />);
    expect(screen.getByText(t('import.excerptAiInput'))).toBeInTheDocument();
    expect(screen.queryByText(t('import.fullAiInput'))).toBeNull();
    rerender(<ImportSourceText text={text} info={importSourceInfo({}, text)} t={t} />);
    expect(screen.getByText(t('import.aiInputUnknown'))).toBeInTheDocument();
    expect(screen.queryByText(t('import.excerptAiInput'))).toBeNull();
  });

  it('closes expanded text when the source changes', () => {
    const t = translate('en');
    const { rerender } = render(<ImportSourceText text="First original" info={importSourceInfo({}, 'First original')} t={t} />);
    fireEvent.click(screen.getByRole('button', { name: t('import.expandSource') }));
    rerender(<ImportSourceText text="New original" info={importSourceInfo({}, 'New original')} t={t} />);
    expect(screen.getByRole('button', { name: t('import.expandSource') })).toHaveAttribute('aria-expanded', 'false');
  });

  it('offers full source in custom cards only, leaving ordinary card presentation unchanged', () => {
    const text = 'Source text. '.repeat(500) + 'LAST PARAGRAPH';
    const custom = customImportToOpp({ id: 'custom-test', imported_at: new Date().toISOString(), opportunity: { ...imported({ description_source: 'page_text', ai_input_scope: 'source_excerpt' }), description_raw: text } });
    const t = translate('zh');
    const props = { selectionMode: false, isSelected: false, selectedSize: 0, isExpanded: true, hasProfile: false,
      onToggleExpand: vi.fn(), onToggleSelect: vi.fn(), onRemove: vi.fn(), onOpenEmailModal: vi.fn(), tailorDisabled: false, t };
    const { rerender } = render(<OpportunityCard {...props} opp={custom} />);
    expect(screen.getByText(t('import.excerptAiInput'))).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: t('import.expandSource') }));
    expect(screen.getByText(/LAST PARAGRAPH/)).not.toHaveClass('line-clamp-4');
    rerender(<OpportunityCard {...props} opp={{ ...{ record_kind: 'listing' }, id: 'canonical', title: 'Listing', opportunity_type: 'internship', source_type: 'campus_program', description_raw: text,
      target_truth: { listing_state: 'open', reference_only: false, actionable: true, accepting_state: 'accepting', reason_code: null, verified_at: null, expires_at: null } }} />);
    expect(screen.queryByRole('button', { name: t('import.expandSource') })).toBeNull();
    expect(screen.queryByText(t('import.excerptAiInput'))).toBeNull();
    expect(screen.getByText(/LAST PARAGRAPH/)).toHaveClass('line-clamp-4');
  });
});
