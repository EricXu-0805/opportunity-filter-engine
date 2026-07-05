import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import CompareTable from './CompareTable';
import { useHasLocalStorageKey, useLocalStorageJSON } from '@/lib/use-local-storage-json';
import type { Opportunity, ProfileData } from '@/lib/types';

vi.mock('@/lib/use-local-storage-json', () => ({
  useHasLocalStorageKey: vi.fn(),
  useLocalStorageJSON: vi.fn(),
}));
vi.mock('./BucketCards', () => ({
  default: () => <div data-testid="bucket-cards" />,
}));
vi.mock('./RadarChart', () => ({
  default: () => <div data-testid="radar-chart" />,
}));

const opps = [
  { id: 'a', title: 'Lab A', organization: 'Org A' },
  { id: 'b', title: 'Lab B', organization: 'Org B' },
] as Opportunity[];

const profile = {
  major: 'CS',
  grade: 'Sophomore',
  is_international: false,
  skills: [{ name: 'Python', level: 'expert' }],
} as ProfileData;

function setStorage(has: boolean | undefined, value: ProfileData | null) {
  vi.mocked(useHasLocalStorageKey).mockReturnValue(has);
  vi.mocked(useLocalStorageJSON).mockReturnValue(value);
}

describe('CompareTable', () => {
  it('shows a loading card while storage is hydrating', () => {
    setStorage(undefined, null);
    render(<CompareTable opps={opps} />);
    expect(screen.getByText('Loading your profile…')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('shows a create-profile CTA plus the profile-independent sections when no profile is stored', () => {
    setStorage(false, null);
    render(<CompareTable opps={opps} />);
    expect(
      screen.getByText('Create a profile to see how these opportunities rank for you.'),
    ).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Create your profile' })).toHaveAttribute('href', '/');
    expect(screen.getByText('Differences')).toBeInTheDocument();
    expect(screen.queryByText('Loading your profile…')).not.toBeInTheDocument();
    expect(screen.queryByTestId('bucket-cards')).not.toBeInTheDocument();
    expect(screen.queryByTestId('radar-chart')).not.toBeInTheDocument();
  });

  it('renders the full ranked comparison when a profile is present', () => {
    setStorage(true, profile);
    render(<CompareTable opps={opps} />);
    expect(screen.getByTestId('bucket-cards')).toBeInTheDocument();
    expect(screen.getByTestId('radar-chart')).toBeInTheDocument();
    expect(screen.getByText('Differences')).toBeInTheDocument();
    expect(screen.queryByText('Loading your profile…')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Create your profile' })).not.toBeInTheDocument();
  });
});
