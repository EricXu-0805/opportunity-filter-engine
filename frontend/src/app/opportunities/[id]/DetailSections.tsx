'use client';

import type { ReactNode } from 'react';
import {
  AlertTriangle,
  Briefcase,
  Calendar,
  Clock,
  DollarSign,
  Globe,
  GraduationCap,
  Mail,
  Users,
} from 'lucide-react';
import type { Opportunity } from '@/lib/types';
import { facultySafeInternational } from '@/lib/match-utils';
import {
  allowsProfessorFraming,
  cleanCompensation,
  friendlyLabel,
  noDeadlineKind,
  type NoDeadlineKind,
} from './detail-utils';
import type { TFunc } from './types';

// Evidence-gated wording for records without a fixed deadline — see
// `noDeadlineKind` in detail-utils.ts. "Rolling" renders only with actual
// scraped rolling evidence; the blanket `is_rolling` default never does.
const NO_DEADLINE_KEYS: Record<NoDeadlineKind, string> = {
  faculty: 'detail.fields.facultyNoOpeningDeadline',
  rolling: 'detail.fields.rollingBasis',
  none: 'detail.fields.noDeadlineListed',
};

export function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="bg-white rounded-2xl shadow-[0_1px_8px_rgba(0,0,0,0.05)] p-5 sm:p-7 mb-4">
      <h2 className="text-[14px] font-semibold text-gray-900 mb-4 tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

export function DetailRow({
  icon,
  label,
  value,
  warn,
  note,
  noteTestId,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  warn?: boolean;
  /** Provenance under the value — where this came from, when it was not the
   *  record's own statement. */
  note?: string;
  noteTestId?: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <span className={`shrink-0 mt-0.5 text-gray-400 ${warn ? 'text-amber-500' : ''}`} aria-hidden="true">
        {icon}
      </span>
      <div className="min-w-0">
        <dt className="text-[11px] text-gray-400 uppercase tracking-wider mb-0.5">{label}</dt>
        <dd className={`text-[14px] break-words ${warn ? 'text-amber-700' : 'text-gray-800'}`}>{value}</dd>
        {note && (
          <dd className="mt-1 text-[11px] text-gray-400" data-testid={noteTestId}>{note}</dd>
        )}
      </div>
    </div>
  );
}

export function DescriptionSection({ description, t }: { description: string; t: TFunc }) {
  if (!description) return null;
  return (
    <Section title={t('detail.sections.description')}>
      <p className="text-[14px] sm:text-[15px] text-gray-700 leading-relaxed whitespace-pre-wrap">
        {description}
      </p>
    </Section>
  );
}

export function AtAGlanceSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const isFaculty = opp.source_type === 'faculty_research';
  const compensation = isFaculty ? '' : cleanCompensation(opp.compensation_details);
  return (
    <Section title={t('detail.sections.atGlance')}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
        {!isFaculty && opp.deadline && (
          <DetailRow
            icon={<Calendar />}
            label={t('detail.fields.deadline')}
            value={opp.deadline_is_estimate
              ? `${opp.deadline} ${t('detail.fields.deadlineEstimate')}`
              : opp.deadline}
          />
        )}
        {(isFaculty || (!opp.deadline && opp.is_rolling)) && (
          <DetailRow
            icon={<Calendar />}
            label={t('detail.fields.deadline')}
            value={t(NO_DEADLINE_KEYS[noDeadlineKind(opp)])}
          />
        )}
        {!isFaculty && opp.start_date && (
          <DetailRow icon={<Calendar />} label={t('detail.fields.startDate')} value={opp.start_date} />
        )}
        {!isFaculty && opp.duration && (
          <DetailRow icon={<Clock />} label={t('detail.fields.duration')} value={opp.duration} />
        )}
        {compensation && (
          <DetailRow icon={<DollarSign />} label={t('detail.fields.compensation')} value={compensation} />
        )}
        {!isFaculty && opp.posted_date && (
          <DetailRow icon={<Calendar />} label={t('detail.fields.posted')} value={opp.posted_date} />
        )}
        {opp.lab_or_program && (
          <DetailRow icon={<Briefcase />} label={t('detail.fields.lab')} value={opp.lab_or_program} />
        )}
        {opp.pi_name && (
          <DetailRow
            icon={<Users />}
            label={t(isFaculty ? 'detail.fields.facultyMember' : 'detail.fields.pi')}
            value={opp.pi_name}
          />
        )}
      </dl>
    </Section>
  );
}

export function EligibilitySection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  if (!opp.eligibility) return null;
  const e = opp.eligibility;
  const isFaculty = opp.source_type === 'faculty_research';
  const effectiveIntl = facultySafeInternational(opp);
  const statedYears = (e.preferred_year ?? []).filter(
    (year) => year.toLowerCase() !== 'unknown',
  );
  return (
    <Section title={t('detail.sections.eligibility')}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
        {!isFaculty && statedYears.length > 0 && (
          <DetailRow
            icon={<GraduationCap />}
            label={t('detail.fields.preferredYear')}
            value={statedYears.join(', ')}
          />
        )}
        {!isFaculty && e.majors?.length > 0 && (
          // Same rule as the skills row: 433 records carry a list our keyword
          // bank wrote from the program's research areas, and #862 already
          // stopped the matcher calling it a stated preference. Printing it
          // under "MAJORS" made the same guess read as the program's terms.
          <DetailRow
            icon={<GraduationCap />}
            label={t(opp.majors_attribution === 'inferred' ? 'detail.fields.majorsApproximate' : 'detail.fields.majors')}
            value={e.majors.join(', ')}
            note={opp.majors_attribution === 'inferred' ? t('detail.majorsInferred') : undefined}
            noteTestId="majors-inferred-note"
          />
        )}
        {!isFaculty && e.skills_required?.length > 0 && (
          // Checked for 'inferred', never for absence — same rule as
          // KeywordsSection. 2,767 records carry a list the LLM tagger wrote
          // from prose that names no skills; "REQUIRED SKILLS / Python /
          // MATLAB" on a wet-lab biology REU was one of them.
          <DetailRow
            icon={<Briefcase />}
            label={t(opp.skills_attribution === 'inferred' ? 'detail.fields.skillsMentioned' : 'detail.fields.skills')}
            value={e.skills_required.join(', ')}
            note={opp.skills_attribution === 'inferred' ? t('detail.skillsInferred') : undefined}
            noteTestId="skills-inferred-note"
          />
        )}
        <DetailRow
          icon={<Globe />}
          label={t('detail.fields.international')}
          value={friendlyLabel(effectiveIntl ?? 'unknown', t)}
        />
        {e.citizenship_required && (
          <DetailRow
            icon={<AlertTriangle />}
            label={t('detail.fields.citizenship')}
            value={t('detail.fields.citizenshipNote')}
            warn
          />
        )}
      </dl>
    </Section>
  );
}

export function ApplicationSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  if (!opp.application) return null;
  const a = opp.application;
  const isFaculty = opp.source_type === 'faculty_research';
  return (
    <Section title={t(isFaculty ? 'detail.sections.outreach' : 'detail.sections.application')}>
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-y-4 gap-x-6">
        {a.contact_method && a.contact_method !== 'unknown' && (
          <DetailRow
            icon={<Mail />}
            label={t(isFaculty ? 'detail.fields.suggestedOutreach' : 'detail.fields.contactMethod')}
            value={a.contact_method}
          />
        )}
        {!isFaculty && a.requires_resume && (
          <DetailRow icon={<Briefcase />} label={t('detail.fields.resume')} value={friendlyLabel(a.requires_resume, t)} />
        )}
        {!isFaculty && a.requires_cover_letter && (
          <DetailRow icon={<Briefcase />} label={t('detail.fields.coverLetter')} value={friendlyLabel(a.requires_cover_letter, t)} />
        )}
        {!isFaculty && a.requires_recommendation && (
          <DetailRow icon={<Users />} label={t('detail.fields.recommendation')} value={friendlyLabel(a.requires_recommendation, t)} />
        )}
        {!isFaculty && a.application_effort && a.application_effort !== 'unknown' && (
          <DetailRow icon={<Clock />} label={t('detail.fields.effort')} value={a.application_effort} />
        )}
      </dl>
    </Section>
  );
}

export function RecentWorksSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  const works = opp.metadata?.recent_works;
  if (!works?.length) return null;
  // Publication trust boundary: only works with explicitly verified
  // attribution may be presented as this professor's publications. The
  // backend already strips unverified works from the detail payload; this
  // gate fails closed on stale caches / older payloads too (name_match,
  // absent, or unknown status → the section does not render at all).
  const verified = opp.metadata?.publication_attribution_status === 'verified_author_id';
  if (!verified) return null;
  return (
    <Section title={t('detail.sections.recentWorks')}>
      <ul className="space-y-2.5">
        {works.slice(0, 5).map((w) => (
          <li key={w.title} className="flex items-baseline gap-2.5 text-[13px] leading-snug">
            {w.year != null && (
              <span className="shrink-0 font-mono text-[11px] text-gray-400 tabular-nums">{w.year}</span>
            )}
            <a
              href={`https://scholar.google.com/scholar?q=${encodeURIComponent(`"${w.title}"`)}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-gray-700 hover:text-indigo-600 hover:underline transition-colors"
            >
              {w.title}
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-4 text-[11px] text-gray-400">
        {/* "this professor's record" only when the scraped rank actually is
            professor-like (or unknown — legacy records); a known non-professor
            rank (e.g. "Senior Lecturer") gets the neutral wording. */}
        {t(allowsProfessorFraming(opp.metadata?.faculty_title)
          ? 'detail.recentWorksNote'
          : 'detail.recentWorksNoteNeutral')}
      </p>
    </Section>
  );
}

export function KeywordsSection({ opp, t }: { opp: Opportunity; t: TFunc }) {
  if (!opp.keywords?.length) return null;
  // Checked for 'inferred', never for absence: a record that never went
  // through enrichment carries nothing here and is stated by default.
  const inferred = opp.keywords_attribution === 'inferred';
  return (
    <Section title={t('detail.sections.keywords')}>
      <div className="flex flex-wrap gap-1.5">
        {opp.keywords.map((k) => (
          <span key={k} className="px-2.5 py-1 rounded-full text-[11px] font-medium bg-gray-100 text-gray-600">
            {k}
          </span>
        ))}
      </div>
      {inferred && (
        <p className="mt-2 text-[11px] text-gray-400" data-testid="keywords-inferred-note">
          {t('detail.keywordsInferred')}
        </p>
      )}
    </Section>
  );
}
