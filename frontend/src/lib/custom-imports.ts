'use client';

import {
  readLocalStorageJSON,
  useLocalStorageJSON,
  writeLocalStorageJSON,
} from './use-local-storage-json';
import { isOwnerTokenValid, type OwnerToken } from './identity-owner';
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

// `token` MUST be captured (via captureOwnerToken()) at the moment the
// caller's own write intent began — e.g. the click handler that triggered
// this import — never re-captured just before calling this function. See
// writeLocalStorageJSON's own doc comment.
//
// Preflight (before readCustomImports() below): a stale token must not
// even READ the current owner's list. Gating only the final write is not
// enough — findExistingImport's dedup check would still compare against
// the CURRENT owner's real entries and could return one of THEIR entries
// (id, imported_at) back to a caller acting on a since-replaced identity.
export function addCustomImport(opp: ImportedOpportunity, token: OwnerToken): CustomImport | null {
  if (!isOwnerTokenValid(token, token.uid)) return null;
  const existing = readCustomImports();
  const dup = findExistingImport(opp, existing);
  if (dup) return dup;
  const entry: CustomImport = {
    id: generateId(),
    imported_at: new Date().toISOString(),
    opportunity: opp,
  };
  // The token can still pass the preflight above yet the write itself
  // fail (quota exceeded, private-mode storage denial) — a caller must be
  // told that, not handed back an entry object that implies it was
  // actually persisted.
  const wrote = writeLocalStorageJSON(STORAGE_KEY, [entry, ...existing], token);
  return wrote ? entry : null;
}

// Returns whether the removal actually took effect — true whether or not
// `id` was found (absence is a benign no-op, not a failure), but false on
// EITHER a stale token OR a write that reached storage and failed there
// (quota, private mode). A caller must treat false as a rejected/retryable
// attempt, never a silent success.
export function removeCustomImport(id: string, token: OwnerToken): boolean {
  if (!isOwnerTokenValid(token, token.uid)) return false;
  const existing = readCustomImports();
  const next = existing.filter((c) => c.id !== id);
  if (next.length === existing.length) return true;
  return writeLocalStorageJSON(STORAGE_KEY, next.length > 0 ? next : null, token);
}
