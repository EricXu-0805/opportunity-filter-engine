import { sha256 } from '@noble/hashes/sha2.js';
import { bytesToHex } from '@noble/hashes/utils.js';
import { MAX_RESUME_TEXT_CHARACTERS } from './resume-input';
import { resumeQuoteMatches, validateExperienceEntries, wellFormedUnicode } from './experience-evidence';
import type { ExperienceEntry } from './types';

export interface MatchExperience {
  id: string;
  revision: number;
  status: 'confirmed';
  source: ExperienceEntry['source']['kind'];
  text: string;
}

/** Read one owner's current snapshot for both the synchronous result cache and
 * first-party requests. Only individually confirmed excerpts may leave the browser. */
export function matchExperienceEntries(entries?: ExperienceEntry[], resumeText?: string): ExperienceEntry[] | null {
  const checked = validateExperienceEntries(entries);
  if (!checked.ok) return null;
  const confirmed = checked.value.filter(entry => entry.status === 'confirmed');
  if (!confirmed.some(entry => entry.source.kind === 'resume')) return confirmed;

  // An older/malformed résumé must not suppress unrelated, independently confirmed work.
  const characters = typeof resumeText === 'string' && resumeText.length <= MAX_RESUME_TEXT_CHARACTERS * 2
    && wellFormedUnicode(resumeText) ? Array.from(resumeText) : [];
  const digest = characters.length > 0 && characters.length <= MAX_RESUME_TEXT_CHARACTERS
    ? bytesToHex(sha256(new TextEncoder().encode(resumeText))) : '';
  return confirmed.filter(entry => entry.source.kind !== 'resume'
    || (entry.source.signature === digest && resumeQuoteMatches(entry.source, characters)));
}

export function matchExperienceRows(entries?: ExperienceEntry[], resumeText?: string): MatchExperience[] | null {
  const eligible = matchExperienceEntries(entries, resumeText);
  return eligible?.map(entry => ({
    id: entry.id, revision: entry.revision, status: 'confirmed', source: entry.source.kind, text: entry.text,
  })) ?? null;
}
