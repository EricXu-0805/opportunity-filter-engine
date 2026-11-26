import { render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { MatchExperienceReceipt } from './MatchExperienceReceipt';
import type { ExperienceEntry } from '@/lib/types';
vi.mock('@/i18n/client', () => ({ useLocale: () => 'en' }));

it('shows the complete exact revision and source, then removes an obsolete or withdrawn result', () => {
  const entry: ExperienceEntry = { id: 'work', revision: 3, status: 'confirmed',
    text: 'Built Python tools for a project. Retained the original organization, role and dates.',
    source: { kind: 'github', repository: 'sample-org/sample', head_repository: null, author: 'sample', number: 41, title: 'Add tools' } };
  const basis = { entry_id: 'work', revision: 3, method: 'Python', target_source: 'stated_requirement' as const };
  const wrapper = render(<MatchExperienceReceipt basis={basis} entries={[entry]} />);
  expect(screen.getByText(entry.text)).toBeInTheDocument();
  expect(screen.getByText('sample-org/sample #41')).toHaveAttribute('href','https://github.com/sample-org/sample/pull/41');
  wrapper.rerender(<MatchExperienceReceipt basis={basis} entries={[{ ...entry, revision: 4 }]} />);
  expect(screen.queryByText(entry.text)).toBeNull();
  wrapper.rerender(<MatchExperienceReceipt basis={basis} entries={[{ ...entry, status: 'withdrawn' }]} />);
  expect(screen.queryByText(entry.text)).toBeNull();
});
