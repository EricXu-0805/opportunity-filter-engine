import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ProfileCompletenessHint } from './ProfileCompletenessHint';
import { ProfileStrength } from '@/app/home/ProfileStrength';
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
    resume_text: '',
    seeking_types: [],
    ...o,
  } as ProfileData;
}

describe('ProfileCompletenessHint', () => {
  it('renders nothing when every signal the student can supply is filled', () => {
    const { container } = render(
      <ProfileCompletenessHint
        profile={makeProfile({
          research_interests: 'ML',
          skills: [{ name: 'Python', level: 'expert' }, { name: 'R', level: 'beginner' }],
          resume_text: 'resume text',
          seeking_types: ['research'],
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
        profile={makeProfile({ research_interests: 'ML' })} // academic + interests: 2 of 5
        onEdit={onEdit}
        t={t}
      />,
    );
    expect(
      screen.getByText(/results\.completeness\.summary\{complete=2,total=5/),
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
          skills: [{ name: 'Python', level: 'expert' }, { name: 'R', level: 'beginner' }],
          resume_text: 'resume text',
          seeking_types: ['research'],
          coursework: [],
        })}
        onEdit={() => {}}
        t={t}
      />,
    );
    expect(screen.queryByText(/coursework/)).toBeNull();
  });
});

describe('the two profile meters cannot disagree', () => {
  it('reads the same list the home page strength meter reads', () => {
    // One profile, both surfaces: what one calls 3/5 the other must too, and
    // the items it names must be the ones the other is missing.
    const profile = makeProfile({
      research_interests: 'ML',
      skills: [{ name: 'Python', level: 'expert' }],   // one skill: not yet 2+
    });
    render(<ProfileCompletenessHint profile={profile} onEdit={() => {}} t={t} />);
    expect(screen.getByText(/results\.completeness\.summary\{complete=2,total=5,missing=/)).toBeInTheDocument();
    const summary = screen.getByText(/results\.completeness\.summary/).textContent ?? '';
    for (const key of ['skills', 'resume', 'type']) {
      expect(summary).toContain(`results.completeness.fields.${key}`);
    }
    expect(summary).not.toContain('results.completeness.fields.interests');
    expect(summary).not.toContain('results.completeness.fields.academic');

    const { container } = render(<ProfileStrength profile={profile} t={t} />);
    expect(container.textContent).toContain('2/5');
  });
});
