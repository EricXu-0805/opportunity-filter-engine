import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import { OnlineProfilesCard } from './OnlineProfilesCard';
import type { ProfileData } from '@/lib/types';

const t = (key: string, vars?: Record<string, string | number>) =>
  vars ? `${key}:${Object.values(vars).join(',')}` : key;

function baseProfile(overrides: Partial<ProfileData> = {}): ProfileData {
  return {
    institution: 'UIUC',
    college: 'Grainger',
    major: 'CS',
    grade: 'Sophomore',
    is_international: false,
    research_interests: '',
    skills: [],
    ...overrides,
  };
}

function renderCard(overrides: Partial<ProfileData> = {}) {
  const update = vi.fn();
  const onGitHubImport = vi.fn();
  render(
    <OnlineProfilesCard
      profile={baseProfile(overrides)}
      update={update}
      ghLoading={false}
      ghStatus={null}
      onGitHubImport={onGitHubImport}
      t={t}
    />,
  );
  return { update, onGitHubImport };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('OnlineProfilesCard — Google Scholar field', () => {
  it('renders the Google Scholar field alongside LinkedIn and GitHub', () => {
    renderCard();
    // Regression: the existing profile fields must still render.
    expect(screen.getByLabelText('home.form.linkedinLabel')).toBeInTheDocument();
    expect(screen.getByLabelText('GitHub')).toBeInTheDocument();
    // The new Scholar field renders as a plain URL input (no import button).
    const scholar = screen.getByLabelText('home.form.scholarLabel');
    expect(scholar).toBeInTheDocument();
    expect(scholar).toHaveAttribute('type', 'url');
    expect(scholar).toHaveAttribute('placeholder', 'home.form.scholarPlaceholder');
  });

  it('shows the stored scholar_url value', () => {
    renderCard({ scholar_url: 'https://scholar.google.com/citations?user=ABC123' });
    expect(screen.getByLabelText('home.form.scholarLabel')).toHaveValue(
      'https://scholar.google.com/citations?user=ABC123',
    );
  });

  it('calls update(scholar_url, …) on input — including URLs with extra query params', () => {
    const { update } = renderCard();
    fireEvent.change(screen.getByLabelText('home.form.scholarLabel'), {
      target: { value: 'https://scholar.google.com/citations?user=ABC123&hl=en' },
    });
    expect(update).toHaveBeenCalledWith(
      'scholar_url',
      'https://scholar.google.com/citations?user=ABC123&hl=en',
    );
  });
});
