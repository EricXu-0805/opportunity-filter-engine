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
  it('renders nothing when every signal the student can supply is filled', () => {
    const { container } = render(
      <ProfileCompletenessHint
        profile={makeProfile({
          research_interests: 'ML',
          skills: [{ name: 'Python', level: 'expert' }],
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
        profile={makeProfile({ research_interests: 'ML' })} // only 1 of 3 filled
        onEdit={onEdit}
        t={t}
      />,
    );
    expect(
      screen.getByText(/results\.completeness\.summary\{complete=1,total=3/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText('results.completeness.edit'));
    expect(onEdit).toHaveBeenCalledTimes(1);
  });

  it('never asks for coursework, which the profile form cannot enter', () => {
    // Three of five testers walking production reported this independently:
    // "Profile 2/4 complete — add coursework, résumé" with an Edit profile
    // link to a form that has no coursework control. profile.coursework is
    // written only by résumé PDF extraction, so a student without a résumé
    // could never clear the item.
    render(
      <ProfileCompletenessHint
        profile={makeProfile({
          research_interests: 'ML',
          skills: [{ name: 'Python', level: 'expert' }],
          resume_text: 'resume text',
          coursework: [],
        })}
        onEdit={() => {}}
        t={t}
      />,
    );
    expect(screen.queryByText(/coursework/)).toBeNull();
  });
});
