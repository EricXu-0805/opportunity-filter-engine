import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { OpportunityCard } from './OpportunityCard';
import type { Opp, TFunc } from './types';

const t = ((key: string) => key) as TFunc;
const noop = () => {};

describe('OpportunityCard faculty trust boundary', () => {
  it('labels a non-professor faculty contact neutrally when expanded', () => {
    render(
      <OpportunityCard
        opp={{
          id: 'faculty-lecturer',
          title: 'Senior Lecturer profile',
          source_type: 'faculty_research',
          pi_name: 'Ada Lovelace',
        }}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded
        hasProfile={false}
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={noop}
        tailorDisabled={false}
        t={t}
      />,
    );
    expect(screen.getByText('card.facultyMember')).toBeInTheDocument();
    expect(screen.queryByText('PI:')).toBeNull();
  });

  it('does not publish poisoned opening requirements when expanded', () => {
    const faculty: Opp = {
      id: 'faculty-ada',
      title: 'Ada profile',
      source_type: 'faculty_research',
      eligibility: {
        international_friendly: 'yes',
        skills_required: ['FAKE_REQUIRED_SKILL'],
      },
    };

    render(
      <OpportunityCard
        opp={faculty}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded
        hasProfile={false}
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={noop}
        tailorDisabled={false}
        t={t}
      />,
    );

    expect(screen.queryByText('FAKE_REQUIRED_SKILL')).toBeNull();
    expect(screen.queryByText('favorites.requiredSkills')).toBeNull();
  });

  it('shows the undergraduate stop precisely and removes Draft Email', () => {
    const openEmail = vi.fn();
    const faculty: Opp = {
      id: 'faculty-unavailable',
      title: 'Unavailable faculty profile',
      source_type: 'faculty_research',
      faculty_availability_status: 'not_accepting_undergraduates',
      url: 'https://faculty.example/profile',
    };

    render(
      <OpportunityCard
        opp={faculty}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded={false}
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={openEmail}
        tailorDisabled={false}
        t={t}
      />,
    );

    expect(screen.getByText('card.facultyNotAcceptingUndergraduates')).toBeInTheDocument();
    expect(screen.queryByText('card.facultyContactUnconfirmed')).toBeNull();
    expect(screen.queryByText('card.draftEmail')).toBeNull();
    expect(openEmail).not.toHaveBeenCalled();
    expect(screen.getByText('card.viewFacultyPage')).toBeInTheDocument();
  });

  it('shows research inactivity but keeps a careful Draft Email path', () => {
    const openEmail = vi.fn();
    render(
      <OpportunityCard
        opp={{
          id: 'faculty-inactive',
          title: 'Faculty profile',
          source_type: 'faculty_research',
          faculty_availability_status: 'research_inactive',
        }}
        selectionMode={false}
        isSelected={false}
        selectedSize={0}
        isExpanded={false}
        hasProfile
        onToggleExpand={noop}
        onToggleSelect={noop}
        onRemove={noop}
        onOpenEmailModal={openEmail}
        tailorDisabled={false}
        t={t}
      />,
    );
    expect(screen.getByText('card.facultyResearchInactive')).toBeInTheDocument();
    expect(screen.getByText('card.draftEmail')).toBeInTheDocument();
  });
});
