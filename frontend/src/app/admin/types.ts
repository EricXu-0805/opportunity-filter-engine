// Page-local types for /admin (R36 split).
// Mirrors the response shapes returned by the FastAPI admin endpoints
// (src/api/admin_routes.py — adminFetch consumers below).

import type { useT } from '@/i18n/client';

export type FieldKey =
  | 'empty_majors'
  | 'empty_keywords'
  | 'empty_description'
  | 'missing_deadline'
  | 'missing_skills';

export interface SourceRow {
  source: string;
  total: number;
  empty_majors?: number;
  empty_keywords?: number;
  empty_description?: number;
  short_description?: number;
  missing_deadline?: number;
  rolling_deadline?: number;
  missing_skills?: number;
  past_deadline?: number;
  stale_verify?: number;
  flagged_inactive?: number;
}

export interface WorstField {
  id: string;
  title: string;
  source: string;
  missing_count: number;
  missing_fields?: FieldKey[];
  url: string;
}

export interface AdminResponse {
  total: number;
  global: Record<string, number>;
  sources: SourceRow[];
  worst_fields: WorstField[];
  generated_at: string;
  data_updated_at?: string | null;
}

export interface HistoryEntry {
  t: string;
  total: number;
  empty_majors?: number;
  empty_keywords?: number;
  missing_deadline?: number;
  rolling_deadline?: number;
  flagged_inactive?: number;
}

export interface CollectorRow {
  source: string;
  status: string;
  fetched?: number;
  new?: number;
  updated?: number;
  error?: string;
  deep?: boolean;
}

export interface CollectorStatus {
  sources: CollectorRow[];
  last_run_at?: string | null;
  duration_seconds?: number;
  total_in_file?: number;
}

export interface CollectorHistorySourceCounts {
  status?: string;
  new?: number;
  updated?: number;
  fetched?: number;
}

export interface CollectorHistoryEntry {
  t?: string;
  duration_seconds?: number;
  total_new?: number;
  total_updated?: number;
  total_in_file?: number;
  sources?: Record<string, CollectorHistorySourceCounts>;
}

export interface HealthAlert {
  level: 'alert' | 'warn';
  kind: string;
  message: string;
  metric?: string;
  current?: number;
  baseline?: number;
  delta?: number;
  pct_jump?: number;
}

export interface HealthResponse {
  ok: boolean;
  alerts: HealthAlert[];
  checked_at: string;
}

export type TriggerStatus = {
  kind: 'idle' | 'busy' | 'ok' | 'err';
  message?: string;
};

export type TFunc = ReturnType<typeof useT>['t'];
