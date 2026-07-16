import type { ProfileData } from '@/lib/types';
import type { useT } from '@/i18n/client';

export type TFunc = ReturnType<typeof useT>['t'];

export const DEFAULT_PROFILE: ProfileData = {
  name: '',
  institution: 'UIUC - University of Illinois Urbana-Champaign',
  home_school: 'uiuc',
  college: '',
  major: '',
  additional_majors: [],
  grade: '',
  is_international: false,
  research_interests: '',
  skills: [],
  search_weight: 50,
};

export const SEEKING_TYPES = ['research', 'summer_program', 'internship', 'fellowship'] as const;
export type SeekingType = typeof SEEKING_TYPES[number];


export type SaveStatus = 'idle' | 'saving' | 'saved';
