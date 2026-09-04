import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Opportunity } from '@/lib/types';

import {
  ApplicationSection,
  AtAGlanceSection,
  EligibilitySection,
  KeywordsSection,
  RecentWorksSection,
} from './DetailSections';

function tFn(key: string) {
  return key;
}

function opp(
  metadata: Partial<Opportunity['metadata']>,
  overrides: Partial<Opportunity> = {},
): Opportunity {
  return {
    id: 'opp-1',
    title: 'Research with Prof X',
    organization: 'UIUC',
    metadata: { is_active: true, confidence_score: 0.9, ...metadata },
    ...overrides,
  } as Opportunity;
}

describe('AtAGlanceSection no-deadline wording', () => {
  it('labels a faculty contact by entity type instead of assuming PI rank', () => {
    render(
      <AtAGlanceSection
        opp={opp(
          { faculty_title: 'Senior Lecturer' },
          { source_type: 'faculty_research', pi_name: 'Ada Lovelace' },
        )}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.facultyMember')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.pi')).not.toBeInTheDocument();
  });

  it('faculty records show no listed opening deadline, never "Rolling"', () => {
    // is_rolling=true is a blanket collector default on faculty records —
    // not scraped evidence of rolling admissions.
    render(
      <AtAGlanceSection
        opp={opp({}, { source_type: 'faculty_research', is_rolling: false })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.facultyNoOpeningDeadline')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.rollingBasis')).not.toBeInTheDocument();
  });

  it('non-faculty records without rolling evidence read "no fixed deadline listed"', () => {
    render(
      <AtAGlanceSection
        opp={opp({}, { source_type: 'campus_program', is_rolling: true })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.noDeadlineListed')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.rollingBasis')).not.toBeInTheDocument();
  });

  it('renders rollingBasis only with scraped rolling evidence in deadline_note', () => {
    render(
      <AtAGlanceSection
        opp={opp(
          { deadline_note: 'Rolling admissions' },
          { source_type: 'campus_program', is_rolling: true },
        )}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.rollingBasis')).toBeInTheDocument();
  });

  it('a poisoned faculty deadline is hidden behind the contact-profile boundary', () => {
    render(
      <AtAGlanceSection
        opp={opp({}, { source_type: 'faculty_research', is_rolling: true, deadline: '2026-10-01' })}
        t={tFn}
      />,
    );
    expect(screen.queryByText('2026-10-01')).not.toBeInTheDocument();
    expect(screen.getByText('detail.fields.facultyNoOpeningDeadline')).toBeInTheDocument();
  });
});

describe('unknown faculty requirements', () => {
  it('does not render the unknown year or effort sentinel as a literal value', () => {
    const faculty = opp({}, {
      source_type: 'faculty_research',
      eligibility: {
        preferred_year: ['unknown'],
        majors: ['Computer Science'],
        skills_required: [],
        international_friendly: 'yes',
        citizenship_required: false,
      },
      application: {
        application_effort: 'unknown',
        requires_resume: 'unknown',
        contact_method: 'email',
      },
    });
    const { unmount } = render(<EligibilitySection opp={faculty} t={tFn} />);
    expect(screen.queryByText('unknown')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.fields.preferredYear')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.fields.majors')).not.toBeInTheDocument();
    expect(screen.queryByText('Computer Science')).not.toBeInTheDocument();
    expect(screen.queryByText('common.yes')).not.toBeInTheDocument();
    expect(screen.getByText('common.notSpecified')).toBeInTheDocument();
    unmount();

    render(<ApplicationSection opp={faculty} t={tFn} />);
    expect(screen.queryByText('unknown')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.fields.effort')).not.toBeInTheDocument();
    expect(screen.getByText('detail.sections.outreach')).toBeInTheDocument();
    expect(screen.getByText('detail.fields.suggestedOutreach')).toBeInTheDocument();
    expect(screen.queryByText('detail.sections.application')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.fields.resume')).not.toBeInTheDocument();
  });
});

describe('RecentWorksSection', () => {
  it('renders nothing when the record has no recent works', () => {
    const { container: none } = render(
      <RecentWorksSection opp={opp({})} t={tFn} />,
    );
    expect(none).toBeEmptyDOMElement();
    const { container: empty } = render(
      <RecentWorksSection opp={opp({ recent_works: [] })} t={tFn} />,
    );
    expect(empty).toBeEmptyDOMElement();
  });

  it('renders title, year, and a quoted Scholar search link per verified work', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: [
            { title: 'Deep Learning for Auditory Cortex Mapping', year: 2026 },
            { title: 'A Study Without a Year', year: null },
          ],
          publication_attribution_status: 'verified_author_id',
        })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.sections.recentWorks')).toBeInTheDocument();
    expect(screen.getByText('2026')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Deep Learning for Auditory Cortex Mapping' });
    expect(link).toHaveAttribute(
      'href',
      `https://scholar.google.com/scholar?q=${encodeURIComponent('"Deep Learning for Auditory Cortex Mapping"')}`,
    );
    expect(link).toHaveAttribute('target', '_blank');
    // year-less work still renders its title
    expect(screen.getByRole('link', { name: 'A Study Without a Year' })).toBeInTheDocument();
  });

  it('renders nothing for unverified attribution (fail closed)', () => {
    const works = [{ title: 'A Borderline Paper', year: 2026 }];
    // Publication trust boundary: name_match, legacy-absent, and unknown
    // statuses must not present the works as this professor's publications —
    // the whole section stays hidden, no label fallback.
    for (const metadata of [
      { recent_works: works, publication_attribution_status: 'name_match' as const },
      { recent_works: works },
      { recent_works: works, publication_attribution_status: 'trust_me' as never },
    ]) {
      const { container, unmount } = render(<RecentWorksSection opp={opp(metadata)} t={tFn} />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it('renders verified works with the publication-record note', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: [{ title: 'A Verified Paper', year: 2026 }],
          publication_attribution_status: 'verified_author_id',
          faculty_title: 'Professor',
        })}
        t={tFn}
      />,
    );
    expect(screen.getByRole('link', { name: 'A Verified Paper' })).toBeInTheDocument();
    expect(screen.getByText('detail.recentWorksNote')).toBeInTheDocument();
  });

  it('uses the rank-neutral note for a known non-professor rank', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: [{ title: 'A Verified Paper', year: 2026 }],
          publication_attribution_status: 'verified_author_id',
          faculty_title: 'Senior Lecturer',
        })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.recentWorksNoteNeutral')).toBeInTheDocument();
    expect(screen.queryByText('detail.recentWorksNote')).not.toBeInTheDocument();
  });

  it('keeps the professor note only for stated professor ranks', () => {
    // W11: an unknown rank gets the neutral note — the professor claim is
    // earned by a stated rank, never defaulted.
    for (const faculty_title of ['Assistant Professor']) {
      const { unmount } = render(
        <RecentWorksSection
          opp={opp({
            recent_works: [{ title: 'A Verified Paper', year: 2026 }],
            publication_attribution_status: 'verified_author_id',
            faculty_title,
          })}
          t={tFn}
        />,
      );
      expect(screen.getByText('detail.recentWorksNote')).toBeInTheDocument();
      unmount();
    }
  });

  it('caps the list at 5 works', () => {
    render(
      <RecentWorksSection
        opp={opp({
          recent_works: Array.from({ length: 8 }, (_, i) => ({
            title: `Paper ${i + 1}`,
            year: 2026 - i,
          })),
          publication_attribution_status: 'verified_author_id',
        })}
        t={tFn}
      />,
    );
    expect(screen.getAllByRole('link')).toHaveLength(5);
    expect(screen.queryByText('Paper 6')).not.toBeInTheDocument();
  });
});


describe('KeywordsSection provenance', () => {
  const kw = ['hydrocarbon exploration and reservoir analysis'];

  it('tells the student when the topics were inferred rather than stated', () => {
    render(
      <KeywordsSection
        opp={opp({}, { keywords: kw, keywords_attribution: 'inferred' })}
        t={tFn}
      />,
    );
    expect(screen.getByTestId('keywords-inferred-note')).toBeInTheDocument();
  });

  it('says nothing extra when the professor stated them', () => {
    // Absence is the default for every record that never went through
    // enrichment. Labelling those too would make the label meaningless.
    render(<KeywordsSection opp={opp({}, { keywords: kw })} t={tFn} />);
    expect(screen.queryByTestId('keywords-inferred-note')).not.toBeInTheDocument();
  });

  it('still renders the keywords themselves when they were inferred', () => {
    // The note is a caveat, not a suppression: these topics are why the
    // student is looking at this professor at all.
    render(
      <KeywordsSection
        opp={opp({}, { keywords: kw, keywords_attribution: 'inferred' })}
        t={tFn}
      />,
    );
    expect(screen.getByText(kw[0])).toBeInTheDocument();
  });
});

describe('EligibilitySection skills provenance', () => {
  // A tester walking production as a JHU biology sophomore read "REQUIRED
  // SKILLS / Python / MATLAB" on a wet-lab summer program whose own page
  // lists only timing and a deadline. 2,767 records carry a list the LLM
  // tagger wrote; #859 stopped the matcher calling it a shortfall, and this
  // stops the page calling it the program's terms.
  const elig = {
    international_friendly: 'unknown', preferred_year: [], majors: [],
    skills_required: ['Python', 'MATLAB'], citizenship_required: false,
  } as unknown as Opportunity['eligibility'];

  it('calls a tagger-written list "skills mentioned" and says where it came from', () => {
    render(
      <EligibilitySection
        opp={opp({}, { source_type: 'summer_program', eligibility: elig, skills_attribution: 'inferred' })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.skillsMentioned')).toBeInTheDocument();
    expect(screen.getByTestId('skills-inferred-note')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.skills')).not.toBeInTheDocument();
  });

  it('says an eligibility restriction is ours rather than the program stated one', () => {
    // An international student who reads "Not open to international students"
    // self-selects out and never applies. 32 live listings carry that pair
    // because the tagger matched a federal-organisation or title substring.
    const elig = {
      majors: [], international_friendly: 'no', citizenship_required: true,
      preferred_year: ['senior'], skills_required: [],
    } as unknown as Opportunity['eligibility'];
    render(
      <EligibilitySection
        opp={opp({}, {
          source_type: 'summer_program', eligibility: elig,
          international_attribution: 'inferred',
          citizenship_attribution: 'inferred',
          preferred_year_attribution: 'inferred',
        })}
        t={tFn}
      />,
    );
    expect(screen.getByTestId('international-inferred-note')).toBeInTheDocument();
    expect(screen.getByTestId('citizenship-inferred-note')).toBeInTheDocument();
    expect(screen.getByTestId('year-inferred-note')).toBeInTheDocument();
    expect(screen.getByText('detail.fields.preferredYearMentioned')).toBeInTheDocument();
  });

  it('leaves a stated restriction unqualified', () => {
    const elig = {
      majors: [], international_friendly: 'no', citizenship_required: true,
      preferred_year: ['senior'], skills_required: [],
    } as unknown as Opportunity['eligibility'];
    render(<EligibilitySection opp={opp({}, { source_type: 'summer_program', eligibility: elig })} t={tFn} />);
    expect(screen.queryByTestId('international-inferred-note')).toBeNull();
    expect(screen.queryByTestId('citizenship-inferred-note')).toBeNull();
    expect(screen.getByText('detail.fields.preferredYear')).toBeInTheDocument();
  });

  it('says a major list is approximate when we wrote it', () => {
    const elig = {
      majors: ['Biology', 'Chemistry'], international_friendly: 'unknown',
      preferred_year: [], skills_required: [], citizenship_required: false,
    } as unknown as Opportunity['eligibility'];
    render(
      <EligibilitySection
        opp={opp({}, { source_type: 'summer_program', eligibility: elig, majors_attribution: 'inferred' })}
        t={tFn}
      />,
    );
    expect(screen.getByText('detail.fields.majorsApproximate')).toBeInTheDocument();
    expect(screen.getByTestId('majors-inferred-note')).toBeInTheDocument();
    expect(screen.queryByText('detail.fields.majors')).toBeNull();
  });

  it('keeps "majors" with no note when the program stated them', () => {
    const elig = {
      majors: ['Biology', 'Chemistry'], international_friendly: 'unknown',
      preferred_year: [], skills_required: [], citizenship_required: false,
    } as unknown as Opportunity['eligibility'];
    render(<EligibilitySection opp={opp({}, { source_type: 'summer_program', eligibility: elig })} t={tFn} />);
    expect(screen.getByText('detail.fields.majors')).toBeInTheDocument();
    expect(screen.queryByTestId('majors-inferred-note')).not.toBeInTheDocument();
  });

  it('keeps "required skills" with no note when the program stated them', () => {
    render(
      <EligibilitySection opp={opp({}, { source_type: 'summer_program', eligibility: elig })} t={tFn} />,
    );
    expect(screen.getByText('detail.fields.skills')).toBeInTheDocument();
    expect(screen.queryByTestId('skills-inferred-note')).not.toBeInTheDocument();
  });
});
