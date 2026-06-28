// Page-local types + constants shared across the /results sub-components
// and hooks. Kept in this directory (not src/lib) because the Filters
// shape is intentionally stricter than the SavedSearchFilters in
// lib/saved-searches.ts (source is a union here, plain string there) —
// the saved-searches loader widens at the boundary.

import { Filter, Zap, Target, TrendingUp, Star } from 'lucide-react';
import type { ScopeValue } from '@/lib/discovery-scope';
import type { ProfileData } from '@/lib/types';

export type Tab = 'all' | 'high_priority' | 'good_match' | 'reach' | 'starred';

export type SortKey = 'score' | 'deadline' | 'newest';

export interface Filters {
  paid: '' | 'yes' | 'no';
  intl: '' | 'yes' | 'no';
  // Any source key present in the corpus ('' = all). Options are derived from
  // the actual match results (see sourceLabel + the FilterRail sourceOptions
  // prop) so newer sources like 'simplify_internships' aren't silently
  // un-filterable; equality-matched in use-results-filters, so a plain string.
  source: string;
  onCampus: '' | 'yes' | 'no';
  deadline: '' | '7' | '14' | '30' | 'passed';
  minScore: number;
  // Discovery scope (PR #187): '' = everything the backend returned,
  // 'campus' = home-school records only, 'open' = open/unknown audience.
  scope: ScopeValue;
}

export const DEFAULT_FILTERS: Filters = {
  paid: '',
  intl: '',
  source: '',
  onCampus: '',
  deadline: '',
  minScore: 0,
  scope: '',
};

export const TABS: {
  key: Tab;
  labelKey: string;
  icon: React.ElementType;
  color: string;
}[] = [
  { key: 'all', labelKey: 'results.tabs.all', icon: Filter, color: 'text-gray-600' },
  { key: 'high_priority', labelKey: 'results.tabs.highPriority', icon: Zap, color: 'text-emerald-600' },
  { key: 'good_match', labelKey: 'results.tabs.goodMatch', icon: Target, color: 'text-indigo-600' },
  { key: 'reach', labelKey: 'results.tabs.reach', icon: TrendingUp, color: 'text-amber-600' },
  { key: 'starred', labelKey: 'results.tabs.starred', icon: Star, color: 'text-amber-500' },
];

// Subset of match-utils SEARCH_ALIASES surfaced in the "(also matching: …)"
// hint under the search box. Intentionally narrower than the expansion
// table — only the bigrams we want to advertise to users live here.
export const SEARCH_ALIASES_FOR_HINT: Record<string, string[]> = {
  ml: ['machine learning'],
  ai: ['artificial intelligence'],
  nlp: ['natural language processing'],
  cv: ['computer vision'],
  dl: ['deep learning'],
  rl: ['reinforcement learning'],
  ds: ['data science'],
  se: ['software engineering'],
  db: ['database'],
  hci: ['human computer interaction'],
  cs: ['computer science'],
  ece: ['electrical'],
};

// Older profiles persisted in localStorage stored skills as plain strings
// instead of { name, level }. Reading them through this union lets the
// migrator widen in one place; everywhere downstream sees ProfileData.
export type LegacyProfileShape = Omit<ProfileData, 'skills'> & {
  skills?: ProfileData['skills'] | string[];
};

export function migrateProfile(raw: LegacyProfileShape | null): ProfileData | null {
  if (!raw) return null;
  if (
    Array.isArray(raw.skills)
    && raw.skills.length > 0
    && typeof raw.skills[0] === 'string'
  ) {
    return {
      ...raw,
      skills: (raw.skills as string[]).map((name) => ({
        name,
        level: 'beginner' as const,
      })),
    } as ProfileData;
  }
  return raw as ProfileData;
}

// i18n translator signature used by every leaf in /results. Kept narrow
// (only the shape callers actually use) so the sub-components don't have
// to import the full useT type surface.
export type TFunc = (
  path: string,
  vars?: Record<string, string | number>,
) => string;

// Known source keys map to a translated label; anything else (newer/RSS
// sources) is humanized from the key so it still reads cleanly in the filter.
const SOURCE_LABEL_KEY: Record<string, string> = {
  uiuc_sro: 'results.filters.sourceUiucSro',
  nsf_reu: 'results.filters.sourceNsfReu',
  uiuc_faculty: 'results.filters.sourceUiucFaculty',
  handshake: 'results.filters.sourceHandshake',
  manual: 'results.filters.sourceManual',
  uiuc_our_rss: 'results.filters.sourceOurRss',
  ucb_urap: 'results.filters.sourceUcbUrap',
  ucb_urap_projects: 'results.filters.sourceUcbUrapProjects',
  // UC Berkeley department faculty directories. One label per collector so the
  // source filter never falls back to a humanized "Ucb <Dept> Faculty" string.
  // Keep in lockstep with the ucb_*_faculty collectors wired in refresh_all.
  ucb_eecs_faculty: 'results.filters.sourceUcbEecsFaculty',
  ucb_stat_faculty: 'results.filters.sourceUcbStatFaculty',
  ucb_chem_faculty: 'results.filters.sourceUcbChemFaculty',
  ucb_cee_faculty: 'results.filters.sourceUcbCeeFaculty',
  ucb_anthro_faculty: 'results.filters.sourceUcbAnthroFaculty',
  ucb_arch_faculty: 'results.filters.sourceUcbArchFaculty',
  ucb_astro_faculty: 'results.filters.sourceUcbAstroFaculty',
  ucb_bioe_faculty: 'results.filters.sourceUcbBioeFaculty',
  ucb_cbe_faculty: 'results.filters.sourceUcbCbeFaculty',
  ucb_dcrp_faculty: 'results.filters.sourceUcbDcrpFaculty',
  ucb_econ_faculty: 'results.filters.sourceUcbEconFaculty',
  ucb_eps_faculty: 'results.filters.sourceUcbEpsFaculty',
  ucb_espm_faculty: 'results.filters.sourceUcbEspmFaculty',
  ucb_ib_faculty: 'results.filters.sourceUcbIbFaculty',
  ucb_ieor_faculty: 'results.filters.sourceUcbIeorFaculty',
  ucb_larch_faculty: 'results.filters.sourceUcbLarchFaculty',
  ucb_law_faculty: 'results.filters.sourceUcbLawFaculty',
  ucb_ling_faculty: 'results.filters.sourceUcbLingFaculty',
  ucb_math_faculty: 'results.filters.sourceUcbMathFaculty',
  ucb_mcb_faculty: 'results.filters.sourceUcbMcbFaculty',
  ucb_me_faculty: 'results.filters.sourceUcbMeFaculty',
  ucb_mse_faculty: 'results.filters.sourceUcbMseFaculty',
  ucb_ne_faculty: 'results.filters.sourceUcbNeFaculty',
  ucb_nst_faculty: 'results.filters.sourceUcbNstFaculty',
  ucb_physics_faculty: 'results.filters.sourceUcbPhysicsFaculty',
  ucb_pmb_faculty: 'results.filters.sourceUcbPmbFaculty',
  ucb_polisci_faculty: 'results.filters.sourceUcbPolisciFaculty',
  ucb_psych_faculty: 'results.filters.sourceUcbPsychFaculty',
  ucb_soc_faculty: 'results.filters.sourceUcbSocFaculty',
  ucb_education_faculty: 'results.filters.sourceUcbEducationFaculty',
  ucb_english_faculty: 'results.filters.sourceUcbEnglishFaculty',
  ucb_geog_faculty: 'results.filters.sourceUcbGeogFaculty',
  ucb_haas_faculty: 'results.filters.sourceUcbHaasFaculty',
  ucb_history_faculty: 'results.filters.sourceUcbHistoryFaculty',
  ucb_journalism_faculty: 'results.filters.sourceUcbJournalismFaculty',
  ucb_philos_faculty: 'results.filters.sourceUcbPhilosFaculty',
  ucb_socwel_faculty: 'results.filters.sourceUcbSocwelFaculty',
  ucb_sph_faculty: 'results.filters.sourceUcbSphFaculty',
  ucb_music_faculty: 'results.filters.sourceUcbMusicFaculty',
  ucb_complit_faculty: 'results.filters.sourceUcbComplitFaculty',
  ucb_german_faculty: 'results.filters.sourceUcbGermanFaculty',
  ucb_french_faculty: 'results.filters.sourceUcbFrenchFaculty',
  ucb_slavic_faculty: 'results.filters.sourceUcbSlavicFaculty',
  ucb_tdps_faculty: 'results.filters.sourceUcbTdpsFaculty',
  ucb_rhetoric_faculty: 'results.filters.sourceUcbRhetoricFaculty',
  ucb_spanish_portuguese_faculty: 'results.filters.sourceUcbSpanishPortugueseFaculty',
  ucb_scandinavian_faculty: 'results.filters.sourceUcbScandinavianFaculty',
  ucb_filmmedia_faculty: 'results.filters.sourceUcbFilmmediaFaculty',
  ucb_classics_faculty: 'results.filters.sourceUcbClassicsFaculty',
  // UC Berkeley campus-wide opportunity graph (campus collector emit buckets).
  ucb_research_programs: 'results.filters.sourceUcbResearchPrograms',
  ucb_external_research: 'results.filters.sourceUcbExternalResearch',
  ucb_labs: 'results.filters.sourceUcbLabs',
  // Campus-graph schools (US-News Top-50 rollout). Same three emit buckets
  // per school. Princeton (#1) is first.
  princeton_research_programs: 'results.filters.sourcePrincetonResearchPrograms',
  princeton_external_research: 'results.filters.sourcePrincetonExternalResearch',
  princeton_labs: 'results.filters.sourcePrincetonLabs',
  umich_research_programs: 'results.filters.sourceUmichResearchPrograms',
  umich_external_research: 'results.filters.sourceUmichExternalResearch',
  umich_labs: 'results.filters.sourceUmichLabs',
  umich_faculty: 'results.filters.sourceUmichFaculty',
};

export function sourceLabel(source: string, t: TFunc): string {
  const key = SOURCE_LABEL_KEY[source];
  if (key) return t(key);
  return source.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}
