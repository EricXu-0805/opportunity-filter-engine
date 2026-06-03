import type { ProfileData } from '@/lib/types';
import type { useT } from '@/i18n/client';

export type TFunc = ReturnType<typeof useT>['t'];

export const DEFAULT_PROFILE: ProfileData = {
  name: '',
  institution: 'UIUC - University of Illinois Urbana-Champaign',
  college: '',
  major: '',
  grade: '',
  is_international: false,
  research_interests: '',
  skills: [],
  search_weight: 50,
};

export const SEEKING_TYPES = ['research', 'summer_program', 'internship', 'fellowship'] as const;
export type SeekingType = typeof SEEKING_TYPES[number];

export const FORMAT_OPTIONS = ['any', 'in-person', 'remote'] as const;
export type FormatOption = typeof FORMAT_OPTIONS[number];

export type SaveStatus = 'idle' | 'saving' | 'saved';
