import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { importSuggestions } from './import-suggestions';
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
    const saved = addCustomImport(opportunity, captureOwnerToken());
    expect(saved).not.toBeNull();
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
