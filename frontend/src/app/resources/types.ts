import { FlaskConical, Cpu, BookOpen, type LucideIcon } from 'lucide-react';

export type LabType = 'wet' | 'dry' | 'humanities';

export interface LabTypeMeta {
  key: LabType;
  icon: LucideIcon;
  ringClass: string;
  textClass: string;
  bgClass: string;
}

export const LAB_TYPES: LabTypeMeta[] = [
  {
    key: 'wet',
    icon: FlaskConical,
    ringClass: 'ring-emerald-200',
    textClass: 'text-emerald-700',
    bgClass: 'bg-emerald-50/60',
  },
  {
    key: 'dry',
    icon: Cpu,
    ringClass: 'ring-indigo-200',
    textClass: 'text-indigo-700',
    bgClass: 'bg-indigo-50/60',
  },
  {
    key: 'humanities',
    icon: BookOpen,
    ringClass: 'ring-amber-200',
    textClass: 'text-amber-700',
    bgClass: 'bg-amber-50/60',
  },
];

export interface DatabaseLink {
  key: string;
  short: string;
  href: string;
  domain: string;
}

export const DATABASES: DatabaseLink[] = [
  {
    key: 'illinoisExperts',
    short: 'IE',
    href: 'https://experts.illinois.edu/',
    domain: 'experts.illinois.edu',
  },
  {
    key: 'nihReporter',
    short: 'NIH',
    href: 'https://reporter.nih.gov/',
    domain: 'reporter.nih.gov',
  },
  {
    key: 'nsfAwards',
    short: 'NSF',
    href: 'https://www.nsf.gov/awardsearch/',
    domain: 'nsf.gov',
  },
  {
    key: 'googleScholar',
    short: 'GS',
    href: 'https://scholar.google.com/',
    domain: 'scholar.google.com',
  },
];

export const TIP_BULLET_ORDER = ['p1', 'p2', 'p3', 'p4'] as const;
