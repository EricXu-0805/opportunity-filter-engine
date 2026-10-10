import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import contract from '@/lib/detail-fields.contract.json';
import { readDetailFields } from '@/lib/detail-fields';
import { DetailFactsSection } from './DetailFactsSection';

const t = (key: string) => key;

function renderCase(name: string, isFaculty = false) {
  const c = contract.cases.find((x) => x.name === name);
  if (!c) throw new Error(`no contract case ${name}`);
  const fields = readDetailFields({ detail_fields: c.detail_fields });
  return render(<DetailFactsSection fields={fields!} isFaculty={isFaculty} t={t} />);
}

function row(field: string, facet: string, state?: string) {
  const rows = screen.getAllByTestId(`fact-${field}-${facet}`);
  const match = state ? rows.find((r) => r.getAttribute('data-state') === state) : rows[0];
  if (!match) throw new Error(`no ${state ?? ''} row for ${field}.${facet}`);
  return match;
}

describe('DetailFactsSection', () => {
  it('shows a source-confirmed field as "Source says"', () => {
    renderCase('sro_structured_listing');
    const citizenship = row('eligibility', 'citizenship', 'source');
    expect(within(citizenship).getByText('detail.facts.state.source')).toBeInTheDocument();
    expect(within(citizenship).getByText('detail.facts.values.citizenshipRequired')).toBeInTheDocument();
    expect(within(row('funding', 'compensation', 'source')).getByText('$7,000')).toBeInTheDocument();
  });

  it('shows a configured campus program value as ours, not the source', () => {
    renderCase('curated_campus_program');
    const majors = row('eligibility', 'majors', 'inferred');
    expect(within(majors).getByText('detail.facts.basis.collector_default')).toBeInTheDocument();
    expect(within(majors).getByText('Biology, Chemistry')).toBeInTheDocument();
    expect(within(majors).queryByText('detail.facts.state.source')).not.toBeInTheDocument();
  });

  it('shows a configured value its page states as the source, in the page\'s words', () => {
    renderCase('configured_program_page_states');
    const paid = row('funding', 'paid', 'source');
    expect(within(paid).getByText('detail.facts.state.source')).toBeInTheDocument();
    expect(within(paid).getByText('detail.facts.values.paidStipend')).toBeInTheDocument();
    expect(within(paid).getByTestId('fact-funding-paid-quote').textContent).toBe('Fellows receive a $5,000 stipend.');
    expect(screen.getByTestId('fact-timing-application_window-quote').textContent)
      .toBe('Applications are due March 1.');
    // Each sentence links the page it was read on: the major's, a passage
    // kept from the eligibility page.
    const majors = row('eligibility', 'majors', 'source');
    expect(within(majors).getByTestId('fact-eligibility-majors-quote').textContent).toBe('Open to Chemistry majors.');
    expect(within(within(majors).getByTestId('fact-eligibility-majors-quote-source')).getByRole('link'))
      .toHaveAttribute('href', 'https://example.edu/programs/fellows/eligibility');
    // Class years the page contradicts stay ours and carry no quote.
    const years = row('eligibility', 'class_year', 'inferred');
    expect(within(years).getByText('detail.facts.basis.collector_default')).toBeInTheDocument();
    expect(screen.queryByTestId('fact-eligibility-class_year-quote')).not.toBeInTheDocument();
  });

  it('dates each quote by when its own page was read', () => {
    const c = contract.cases.find((x) => x.name === 'configured_program_page_states')!;
    const fields = readDetailFields({ detail_fields: c.detail_fields })!;
    const dated = (key: string, vars?: Record<string, string | number>) => (vars ? `${key} ${vars.date}` : key);
    render(<DetailFactsSection fields={fields} isFaculty={false} t={dated as typeof t} />);
    expect(screen.getByTestId('fact-eligibility-majors-quote-source')).toHaveTextContent(
      'detail.facts.observed 2026-09-02');
    expect(screen.getByTestId('fact-funding-paid-quote-source')).toHaveTextContent('detail.facts.observed 2026-09-01');
  });

  it('labels an inferred field "System inference" and says how we inferred it', () => {
    renderCase('simplify_internship_template');
    const paid = row('funding', 'paid', 'inferred');
    expect(within(paid).getByText('detail.facts.state.inferred')).toBeInTheDocument();
    expect(within(paid).getByText('detail.facts.basis.collector_default')).toBeInTheDocument();
    expect(within(paid).queryByText('detail.facts.state.source')).not.toBeInTheDocument();
  });

  it('shows a missing field as "Not provided"', () => {
    renderCase('legacy_sparse');
    const dept = row('department', 'department');
    expect(dept.getAttribute('data-state')).toBe('unknown');
    expect(within(dept).getAllByText('detail.facts.state.unknown').length).toBeGreaterThan(0);
  });

  it('does not treat unknown eligibility as ineligible', () => {
    renderCase('stamped_listing');
    const intl = row('eligibility', 'international_students');
    expect(intl.getAttribute('data-state')).toBe('unknown');
    expect(within(intl).getByText('detail.facts.unknownHint.international_students')).toBeInTheDocument();
    expect(screen.queryByText('detail.facts.values.intlNo')).not.toBeInTheDocument();
    expect(screen.queryByText('detail.facts.values.citizenshipRequired')).not.toBeInTheDocument();
  });

  it('does not treat unknown funding as unpaid', () => {
    renderCase('faculty_profile', true);
    const paid = row('funding', 'paid');
    expect(paid.getAttribute('data-state')).toBe('unknown');
    expect(within(paid).getByText('detail.facts.unknownHint.paid')).toBeInTheDocument();
    expect(screen.queryByText('detail.facts.values.paidNo')).not.toBeInTheDocument();
  });

  it('does not treat a missing deadline as "no deadline"', () => {
    renderCase('simplify_internship_template');
    const deadline = row('timing', 'deadline');
    expect(deadline.getAttribute('data-state')).toBe('unknown');
    expect(within(deadline).getByText('detail.facts.unknownHint.deadline')).toBeInTheDocument();
    expect(row('timing', 'rolling').getAttribute('data-state')).toBe('unknown');
  });

  it('does not use the school location as the opportunity location', () => {
    renderCase('curated_campus_program');
    const location = row('location', 'location');
    expect(location.getAttribute('data-state')).toBe('unknown');
    expect(screen.queryByText('Durham, NC')).not.toBeInTheDocument();
    expect(within(location).getByText('detail.facts.unknownHint.location')).toBeInTheDocument();
  });

  it('shows inferred skills as mentioned, never as required', () => {
    renderCase('simplify_internship_template');
    expect(row('required_skills', 'required').getAttribute('data-state')).toBe('unknown');
    const mentioned = row('required_skills', 'mentioned', 'inferred');
    expect(within(mentioned).getByText('detail.facts.facets.mentioned')).toBeInTheDocument();
    expect(within(mentioned).getByText('Python, Java')).toBeInTheDocument();
  });

  it('shows a stated research summary and our derived topics as two rows', () => {
    renderCase('faculty_profile', true);
    expect(within(row('research_content', 'research_areas', 'source')).getByText('Analytical engines; number theory')).toBeInTheDocument();
    expect(within(row('research_content', 'research_areas', 'inferred')).getByText('detail.facts.basis.external_enrichment')).toBeInTheDocument();
    expect(screen.getByTestId('facts-faculty-note')).toBeInTheDocument();
  });

  // M59 (axe definition-list + dlitem, serious): the label and its state tag
  // shared a wrapper <div> inside the row, so no list held a dt/dd group and a
  // screen reader announced neither terms nor their values as a list.
  it.each(contract.cases.map((c) => c.name))('keeps every fact row a dt/dd group (%s)', (name) => {
    const { container } = renderCase(name);
    const lists = container.querySelectorAll('dl');
    expect(lists.length).toBeGreaterThan(0);
    for (const list of lists) {
      for (const group of list.children) {
        const tags = [...group.children].map((child) => child.tagName);
        expect(group.tagName).toBe('DIV');
        expect(tags[0]).toBe('DT');
        expect(tags).toContain('DD');
        expect(tags.every((tag) => tag === 'DT' || tag === 'DD')).toBe(true);
      }
    }
    const majors = row('eligibility', 'majors');
    expect(within(majors).getByRole('term')).toHaveTextContent('detail.facts.facets.majors');
  });

  it('carries provenance on a known field and none on an unknown one', () => {
    renderCase('curated_campus_program');
    const school = screen.getByTestId('fact-field-school');
    expect(within(school).getByText('detail.facts.sourceLink').closest('a')?.getAttribute('href'))
      .toBe('https://example.edu/programs/surf');
    expect(within(school).getByText('detail.facts.observed')).toBeInTheDocument();
    const location = screen.getByTestId('fact-field-location');
    expect(within(location).queryByText('detail.facts.sourceLink')).not.toBeInTheDocument();
  });
});
