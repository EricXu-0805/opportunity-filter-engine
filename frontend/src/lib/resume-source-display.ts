import type { ExperienceEntry, ResumeFact } from './types';
import { isActiveResumeFact } from './resume-master';
import { isActiveExperience, type ExperienceSourceContext } from './experience-evidence';

export type ResumeSourceDisplayState = 'current' | 'candidate' | 'withdrawn' | 'rejected' | 'checking' | 'source_changed';
/** A retained value is not automatically a current fact. The UI keeps the
 * record selectable by ID while withholding outdated labels and source text. */
export function resumeSourceDisplayState(item: ResumeFact | ExperienceEntry,
  context: ExperienceSourceContext | null): ResumeSourceDisplayState {
  if (item.status === 'candidate') return 'candidate';
  if (item.status === 'withdrawn') return 'withdrawn';
  if (item.status === 'rejected') return 'rejected';
  if (item.source.kind === 'resume' && !context) return 'checking';
  const currentContext = context ?? { rawText: '', expectedDigest: '' };
  const active = 'value' in item ? isActiveResumeFact(item, currentContext) : isActiveExperience(item, currentContext);
  return active ? 'current' : 'source_changed';
}
