import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { dictionaries } from '@/i18n/dictionaries';
import type { ImportedOpportunity } from '@/lib/api';
import ImportOpportunityDetails from './ImportOpportunityDetails';

function translator(locale: 'en' | 'zh') {
  return (key: string) => String(key.split('.').reduce<unknown>((value, part) => (value as Record<string, unknown>)[part], dictionaries[locale]));
}

const opportunity: ImportedOpportunity = {
  source: 'url_parser', source_url: 'https://example.edu/p', url: 'https://example.edu/p', title: 'Summer lab',
  description_raw: 'We welcome applicants.', organization: 'Example University', deadline: '2027-01-15',
  extra_fields: {
    international_friendly: 'yes', preferred_year: ['junior'], paid: 'yes',
    inferred_fields: { deadline: 'llm:url_parser', international_friendly: 'llm:url_parser', preferred_year: 'llm:url_parser' },
  },
};

function row(label: string) {
  return screen.getByText(label).closest('div') as HTMLElement;
}

describe('imported opportunity fields', () => {
  it.each(['en', 'zh'] as const)('%s marks guessed fields and leaves source fields unmarked', (locale) => {
    const t = translator(locale);
    render(<ImportOpportunityDetails opportunity={opportunity} t={t} />);
    const guess = t('import.fieldInferred');
    for (const label of ['import.fieldIntl', 'import.fieldYear', 'import.fieldDeadline']) {
      expect(row(t(label))).toHaveTextContent(guess);
    }
    for (const label of ['import.fieldOrg', 'import.fieldPaid']) {
      expect(row(t(label))).not.toHaveTextContent(guess);
    }
  });

  it('does not mark a field the model guessed but left empty', () => {
    const t = translator('en');
    render(<ImportOpportunityDetails opportunity={{ ...opportunity, deadline: null }} t={t} />);
    expect(row(t('import.fieldDeadline'))).not.toHaveTextContent(t('import.fieldInferred'));
  });
});
