'use client';

import {
  readLocalStorageJSON,
  useLocalStorageJSON,
  writeLocalStorageJSON,
} from './use-local-storage-json';
import { STORAGE_KEYS } from './storage-keys';
import type { ImportedOpportunity } from './api';

const STORAGE_KEY = STORAGE_KEYS.CUSTOM_IMPORTS;

export interface CustomImport {
  id: string;
  imported_at: string;
  opportunity: ImportedOpportunity;
}

export function useCustomImports(): CustomImport[] {
  return useLocalStorageJSON<CustomImport[]>(STORAGE_KEY) ?? [];
}

export function readCustomImports(): CustomImport[] {
  return readLocalStorageJSON<CustomImport[]>(STORAGE_KEY) ?? [];
}

function generateId(): string {
  const rand = Math.random().toString(36).slice(2, 8);
  return `custom-${Date.now()}-${rand}`;
}

// Returns the existing record when this opportunity (by source_url, or
// title+org when no URL) is already saved — so callers can show "Already
// saved" UX instead of writing a duplicate.
export function findExistingImport(
  opp: ImportedOpportunity,
  list: CustomImport[] = readCustomImports(),
): CustomImport | null {
  for (const entry of list) {
    if (isSameOpportunity(entry.opportunity, opp)) return entry;
  }
  return null;
}

function isSameOpportunity(a: ImportedOpportunity, b: ImportedOpportunity): boolean {
  const aUrl = (a.source_url || a.url || '').trim();
  const bUrl = (b.source_url || b.url || '').trim();
  if (aUrl && bUrl) return aUrl === bUrl;
  const aTitle = (a.title || '').trim();
  const bTitle = (b.title || '').trim();
  if (!aTitle || !bTitle) return false;
  const aOrg = (a.organization || '').trim();
  const bOrg = (b.organization || '').trim();
  return aTitle === bTitle && aOrg === bOrg;
}

export function addCustomImport(opp: ImportedOpportunity): CustomImport {
  const existing = readCustomImports();
  const dup = findExistingImport(opp, existing);
  if (dup) return dup;
  const entry: CustomImport = {
    id: generateId(),
    imported_at: new Date().toISOString(),
    opportunity: opp,
  };
  writeLocalStorageJSON(STORAGE_KEY, [entry, ...existing]);
  return entry;
}

export function removeCustomImport(id: string): void {
  const existing = readCustomImports();
  const next = existing.filter((c) => c.id !== id);
  if (next.length === existing.length) return;
  writeLocalStorageJSON(STORAGE_KEY, next.length > 0 ? next : null);
}
