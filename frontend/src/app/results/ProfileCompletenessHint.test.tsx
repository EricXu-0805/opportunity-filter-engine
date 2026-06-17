import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ProfileCompletenessHint } from './ProfileCompletenessHint';
import type { ProfileData } from '@/lib/types';

const t = (k: string, vars?: Record<string, string | number>) =>
  vars ? `${k}{${Object.entries(vars).map(([a, b]) => `${a}=${b}`).join(',')}}` : k;

function makeProfile(o: Partial<ProfileData> = {}): ProfileData {
  return {
    institution: 'UIUC',
    college: 'Grainger',
    major: 'CS',
    grade: 'Sophomore',
    is_international: false,
    research_interests: '',
    skills: [],
    coursework: [],
    resume_text: '',
    ...o,
  } as ProfileData;
}

describe('ProfileCompletenessHint', () => {
  it('renders nothing when all four signals are filled', () => {
    const { container } = render(
      <ProfileCompletenessHint
        profile={makeProfile({
          research_interests: 'ML',
          skills: [{ name: 'Python', level: 'expert' }],
          coursework: ['CS 225'],
          resume_text: 'resume text',
        })}
        onEdit={() => {}}
        t={t}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('shows the complete/total count when thin and fires onEdit', () => {
    const onEdit = vi.fn();
    render(
      <ProfileCompletenessHint
        profile={makeProfile({ research_interests: 'ML' })} // only 1 of 4 filled
        onEdit={onEdit}
        t={t}
      />,
    );
    expect(
      screen.getByText(/results\.completeness\.summary\{complete=1,total=4/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText('results.completeness.edit'));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });
});
