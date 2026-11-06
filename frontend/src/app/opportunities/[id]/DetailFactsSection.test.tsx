import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import contract from '@/lib/detail-fields.contract.json';
import { translate } from '@/i18n/translate';
import { DETAIL_FIELDS_VERSION, readDetailFields } from '@/lib/detail-fields';
import { DetailFactsSection } from './DetailFactsSection';

const t = (key: string) => key;

function renderCase(name: string, isFaculty = false, translateKey: (key: string) => string = t) {
  const c = contract.cases.find((x) => x.name === name);
  if (!c) throw new Error(`no contract case ${name}`);
  const fields = readDetailFields({ detail_fields: c.detail_fields });
  return render(<DetailFactsSection fields={fields!} isFaculty={isFaculty} t={translateKey} />);
}

function row(field: string, facet: string, state?: string) {
  const rows = screen.getAllByTestId(`fact-${field}-${facet}`);
  const match = state ? rows.find((r) => r.getAttribute('data-state') === state) : rows[0];
  if (!match) throw new Error(`no ${state ?? ''} row for ${field}.${facet}`);
  return match;
}

describe('DetailFactsSection', () => {
  it.each(['en', 'zh'] as const)('keeps profile evidence under stated research only (%s)', (locale) => {
    const c = contract.cases.find((x) => x.name === 'faculty_profile')!;
    const fields = readDetailFields({ detail_fields: c.detail_fields })!;
    render(<DetailFactsSection fields={fields} isFaculty t={(key, vars) => translate(locale, key, vars)} />);
    const stated = row('research_content', 'research_areas', 'source');
    const inferred = row('research_content', 'research_areas', 'inferred');
    expect(within(stated).getByRole('link')).toHaveAttribute('href', 'https://example.edu/people/ada');
    expect(stated).toHaveTextContent('2026-09-01');
    expect(within(inferred).queryByRole('link')).not.toBeInTheDocument();
    expect(inferred).not.toHaveTextContent('2026-09-01');
    // No second, shared footer below both rows.
    expect(within(screen.getByTestId('fact-field-research_content')).getAllByRole('link')).toHaveLength(1);
  });

  it.each(['OpenAlex', 'Illinois Experts', 'unrecognized provider', undefined])(
    'does not cite the personal page for external-only topics (%s)', (sourceName) => {
      const fields = readDetailFields({ detail_fields: {
        version: DETAIL_FIELDS_VERSION,
        fields: { research_content: {
          inferred: { research_areas: { value: ['Genomics'], basis: 'external_enrichment', source_name: sourceName } },
          // An older API can still send the misleading field-level footer.
          provenance: { source_url: 'https://example.edu/people/ada', observed_at: '2026-10-26' },
        } },
      } })!;
      render(<DetailFactsSection fields={fields} isFaculty t={(key, vars) => translate('en', key, vars)} />);
      const group = screen.getByTestId('fact-field-research_content');
      expect(within(group).queryByRole('link')).not.toBeInTheDocument();
      expect(group).not.toHaveTextContent('2026-10-26');
      expect(group).toHaveTextContent('System inference');
      expect(group).toHaveTextContent(sourceName === 'OpenAlex' || sourceName === 'Illinois Experts'
        ? `Topics inferred from a matched ${sourceName} record` : 'From a matched external record');
      expect(group).not.toHaveTextContent('unrecognized provider');
    },
  );

  it('keeps a research quote on its own URL and date beside external topics', () => {
    const fields = readDetailFields({ detail_fields: {
      version: DETAIL_FIELDS_VERSION,
      fields: { research_content: {
        explicit: { research_areas: 'Genomics' },
        inferred: { research_areas: { value: ['Genetics'], basis: 'external_enrichment', source_name: 'Illinois Experts' } },
        quotes: { research_areas: { text: 'Our group studies genomics.', source_url: 'https://example.edu/lab', observed_at: '2026-10-20' } },
        provenance: { source_url: 'https://example.edu/people/ada', observed_at: '2026-10-26' },
      } },
    } })!;
    render(<DetailFactsSection fields={fields} isFaculty t={(key, vars) => translate('zh', key, vars)} />);
    const stated = row('research_content', 'research_areas', 'source');
    expect(within(stated).getByRole('link')).toHaveAttribute('href', 'https://example.edu/lab');
    expect(stated).toHaveTextContent('2026-10-20');
    expect(row('research_content', 'research_areas', 'inferred')).toHaveTextContent('根据匹配到的 Illinois Experts 记录推断的研究方向');
    const group = screen.getByTestId('fact-field-research_content');
    expect(group).not.toHaveTextContent('2026-10-26');
    expect(within(group).getAllByRole('link')).toHaveLength(1);
  });

  it('keeps the observed date under stated research beside external topics when there is no page link', () => {
    const fields = readDetailFields({ detail_fields: {
      version: DETAIL_FIELDS_VERSION,
      fields: { research_content: {
        explicit: { research_areas: 'Genomics' },
        inferred: { research_areas: { value: ['Genetics'], basis: 'external_enrichment', source_name: 'OpenAlex' } },
        provenance: { source_url: null, observed_at: '2026-10-26' },
      } },
    } })!;
    render(<DetailFactsSection fields={fields} isFaculty t={(key, vars) => translate('en', key, vars)} />);
    expect(row('research_content', 'research_areas', 'source')).toHaveTextContent('Observed 2026-10-26');
    expect(row('research_content', 'research_areas', 'inferred')).not.toHaveTextContent('2026-10-26');
    const group = screen.getByTestId('fact-field-research_content');
    expect(within(group).getAllByText(/2026-10-26/)).toHaveLength(1);
    expect(within(group).queryByRole('link')).not.toBeInTheDocument();
  });

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
    expect(within(majors).getByText('detail.majorsConfigured')).toBeInTheDocument();
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
    expect(within(years).getByText('detail.yearConfigured')).toBeInTheDocument();
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

  // purdue-7dc8e5d17382 (2026-10-12): the program's own major and class-year
  // lists, from our config, read "A default we apply to this source" — a
  // constant on every row, which they are not.
  it.each([
    ['en', 'System inference', 'From our listing’s major list. Check the program’s eligibility requirements.',
      'From our listing’s class-year list. Check the program’s eligibility requirements.', 'A default we apply to this source'],
    ['zh', '系统推断', '来自本站整理的专业清单，申请资格请核对项目要求。', '来自本站整理的年级清单，申请资格请核对项目要求。',
      '我们对该来源使用的默认值'],
  ] as const)('says a configured major or class-year list is our listing\'s (%s)', (locale, inferred, majorsNote, yearNote, sourceDefault) => {
    const fields = readDetailFields({
      detail_fields: {
        version: DETAIL_FIELDS_VERSION,
        fields: {
          eligibility: {
            state: 'inferred',
            explicit: {},
            inferred: {
              majors: { value: ['Engineering', 'Computer Science'], basis: 'configured' },
              class_year: { value: ['sophomore', 'junior'], basis: 'configured' },
            },
            unknown: ['min_gpa', 'international_students', 'citizenship', 'work_authorization_notes'],
          },
        },
      },
    });
    render(<DetailFactsSection fields={fields!} isFaculty={false} t={(key) => translate(locale, key)} />);
    const majors = row('eligibility', 'majors', 'inferred');
    expect(within(majors).getByText(inferred)).toBeInTheDocument();
    expect(within(majors).getByText('Engineering, Computer Science')).toBeInTheDocument();
    expect(within(majors).getByTestId('fact-eligibility-majors-basis')).toHaveTextContent(majorsNote);
    expect(within(row('eligibility', 'class_year', 'inferred')).getByTestId('fact-eligibility-class_year-basis'))
      .toHaveTextContent(yearNote);
    expect(screen.queryByText(sourceDefault)).not.toBeInTheDocument();
  });

  // purdue-af71941ba814 (2026-10-12): a program's own pay, intl answer,
  // citizenship rule and deadline note, from our config, read "A default we
  // apply to this source" like the stipend Simplify writes on every row.
  it.each([
    ['en', 'From our listing’s entry for this program. Check the program’s current information.',
      'From our listing’s deadline note. Check the program’s current dates.', 'A default we apply to this source'],
    ['zh', '来自本站整理的项目信息，当前情况请核对项目页面。', '来自本站整理的截止说明，当前日期请核对项目页面。',
      '我们对该来源使用的默认值'],
  ] as const)('says a configured pay, intl, citizenship or deadline note is our listing\'s (%s)', (locale, entryNote, noteNote, sourceDefault) => {
    const translateKey = (key: string) => translate(locale, key);
    const { unmount } = renderCase('curated_campus_program', false, translateKey);
    for (const [field, facet] of [
      ['funding', 'paid'], ['funding', 'compensation'], ['eligibility', 'international_students'],
    ] as const) {
      expect(within(row(field, facet, 'inferred')).getByTestId(`fact-${field}-${facet}-basis`))
        .toHaveTextContent(entryNote);
    }
    for (const facet of ['application_window', 'rolling']) {
      expect(within(row('timing', facet, 'inferred')).getByTestId(`fact-timing-${facet}-basis`))
        .toHaveTextContent(noteNote);
    }
    // The contact method every collector writes is a real source default.
    expect(screen.getByTestId('fact-application_method-contact_method-basis')).toHaveTextContent(sourceDefault);
    unmount();
    const fields = readDetailFields({
      detail_fields: {
        version: DETAIL_FIELDS_VERSION,
        fields: {
          eligibility: {
            state: 'inferred',
            explicit: {},
            inferred: { citizenship: { value: 'required', basis: 'configured' } },
            unknown: ['class_year', 'majors', 'min_gpa', 'international_students', 'work_authorization_notes'],
          },
        },
      },
    });
    render(<DetailFactsSection fields={fields!} isFaculty={false} t={translateKey} />);
    expect(within(row('eligibility', 'citizenship', 'inferred')).getByTestId('fact-eligibility-citizenship-basis'))
      .toHaveTextContent(entryNote);
  });

  // Simplify's majors and topics come from a map keyed on its category, and a
  // program spec's topics are tags we typed: none was read off a page, and
  // the facts said "Read from the page text by our pipeline".
  it.each([
    ['en', 'Tagged by our system', 'Read from the page text by our pipeline'],
    ['zh', '由我们的系统标注', '由我们的程序从页面文字中读取'],
  ] as const)('says tags we assign are tagged by our system, not read from the page (%s)', (locale, tagged, scanned) => {
    const translateKey = (key: string) => translate(locale, key);
    const { unmount } = renderCase('simplify_internship_template', false, translateKey);
    expect(within(row('eligibility', 'majors', 'inferred')).getByTestId('fact-eligibility-majors-basis'))
      .toHaveTextContent(tagged);
    expect(within(row('research_content', 'research_areas', 'inferred'))
      .getByTestId('fact-research_content-research_areas-basis')).toHaveTextContent(tagged);
    // Skills a tagger read out of the text keep the reading label.
    expect(within(row('required_skills', 'mentioned', 'inferred')).getByTestId('fact-required_skills-mentioned-basis'))
      .toHaveTextContent(scanned);
    unmount();
    renderCase('curated_campus_program', false, translateKey);
    expect(within(row('research_content', 'research_areas', 'inferred'))
      .getByTestId('fact-research_content-research_areas-basis')).toHaveTextContent(tagged);
  });

  it('labels an inferred field "System inference" and says how we inferred it', () => {
    renderCase('simplify_internship_template');
    const paid = row('funding', 'paid', 'inferred');
    expect(within(paid).getByText('detail.facts.state.inferred')).toBeInTheDocument();
    expect(within(paid).getByText('detail.facts.basis.collector_default')).toBeInTheDocument();
    expect(within(paid).queryByText('detail.facts.state.source')).not.toBeInTheDocument();
  });

  it('says a Simplify listing\'s "Does Not Offer Sponsorship" label, still as our inference', () => {
    // M121: the label is not "not open to international students".
    const c = contract.cases.find((x) => x.name === 'simplify_internship_template')!;
    const fields = readDetailFields({ detail_fields: c.detail_fields })!;
    const { unmount } = render(<DetailFactsSection fields={fields} isFaculty={false} noSponsorship t={t} />);
    const intl = row('eligibility', 'international_students', 'inferred');
    expect(within(intl).getByText('detail.facts.values.intlNoSponsorship')).toBeInTheDocument();
    expect(within(intl).getByText('detail.facts.state.inferred')).toBeInTheDocument();
    expect(within(intl).getByText('detail.facts.basis.derived_from_source')).toBeInTheDocument();
    expect(screen.queryByText('detail.facts.values.intlNo')).not.toBeInTheDocument();
    unmount();
    for (const [locale, text] of [['en', 'No visa sponsorship (listing label)'], ['zh', '不提供签证担保（职位信息标注）']] as const) {
      const view = render(
        <DetailFactsSection fields={fields} isFaculty={false} noSponsorship t={(key) => translate(locale, key)} />,
      );
      expect(row('eligibility', 'international_students', 'inferred')).toHaveTextContent(text);
      view.unmount();
    }
  });

  it('keeps "Not open to international students" for every other "no"', () => {
    for (const name of ['simplify_internship_template', 'sro_structured_listing', 'nsf_reu_policy']) {
      const view = renderCase(name);
      const intl = row('eligibility', 'international_students', 'inferred');
      expect(within(intl).getByText('detail.facts.values.intlNo'), name).toBeInTheDocument();
      expect(screen.queryByText('detail.facts.values.intlNoSponsorship'), name).not.toBeInTheDocument();
      view.unmount();
    }
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
    expect(within(row('research_content', 'research_areas', 'inferred')).getByText('detail.facts.externalSource')).toBeInTheDocument();
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

describe('a program whose page states an opening still ahead', () => {
  const OPENING = {
    on: '2026-11-15', at: '2999-11-15T06:00:00+00:00', text: 'November 15',
    quote: 'November 15: Online application opens.', source_url: 'https://summerprogram.unl.edu/',
  };
  const fields = () => readDetailFields({ detail_fields: {
    version: DETAIL_FIELDS_VERSION,
    fields: {
      timing: {
        explicit: { deadline: '2027-03-01' },
        quotes: { deadline: { text: 'March 1: Application deadline.', source_url: 'https://summerprogram.unl.edu/', observed_at: '2026-11-05' } },
      },
      application_method: { explicit: { application_url: 'https://summerprogram.unl.edu/' } },
    },
  } })!;

  it.each([['en', 'Applications open'], ['zh', '申请开放日']] as const)(
    'gives the opening among the timing facts, in the page\'s words (%s)', (locale, label) => {
      render(
        <DetailFactsSection fields={fields()} isFaculty={false} opening={OPENING}
          t={(key, vars) => translate(locale, key, vars)} />,
      );
      const opens = row('timing', 'application_opens', 'source');
      expect(within(screen.getByTestId('fact-field-timing')).getByTestId('fact-timing-application_opens')).toBe(opens);
      expect(opens).toHaveTextContent(label);
      expect(within(opens).getByText('November 15')).toBeInTheDocument();
      expect(within(opens).getByTestId('fact-timing-application_opens-quote').textContent)
        .toBe('November 15: Online application opens.');
      expect(within(opens).getByRole('link')).toHaveAttribute('href', 'https://summerprogram.unl.edu/');
    },
  );

  it('gives no opening row when none is ahead', () => {
    render(<DetailFactsSection fields={fields()} isFaculty={false} t={t} />);
    expect(screen.queryByTestId('fact-timing-application_opens')).toBeNull();
  });
});
