'use client';

import {
  readLocalStorageJSON,
  useLocalStorageJSON,
  writeLocalStorageJSON,
} from './use-local-storage-json';
import { isOwnerTokenValid, readUserScopedEntry, type OwnerToken } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import type { ImportedOpportunity } from './api';

const STORAGE_KEY = STORAGE_KEYS.CUSTOM_IMPORTS;

export interface CustomImport {
  id: string;
  imported_at: string;
  updated_at?: string;
  opportunity: ImportedOpportunity;
}

const EMPTY_IMPORTS: CustomImport[] = [];

// Display filtering is read-only. Mutations use the authoritative strict reader
// below, so a malformed value is never mistaken for an empty writable store.
function displayImports(value: unknown): CustomImport[] {
  if (!Array.isArray(value)) return EMPTY_IMPORTS;
  return value.every(isImportEntry) ? value : value.filter(isImportEntry);
}

export function useCustomImports(): CustomImport[] {
  return useLocalStorageJSON<unknown, CustomImport[]>(STORAGE_KEY, displayImports);
}

export function readCustomImports(): CustomImport[] {
  return readLocalStorageJSON<unknown, CustomImport[]>(STORAGE_KEY, displayImports);
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
  if (!isOpportunityValue(opp) || !Array.isArray(list)) return null;
  for (const entry of list) {
    if (isImportEntry(entry) && isSameOpportunity(entry.opportunity, opp)) return entry;
  }
  return null;
}

function isSameOpportunity(a: ImportedOpportunity, b: ImportedOpportunity): boolean {
  const aUrl = (a.source_url || a.url || '').trim();
  const bUrl = (b.source_url || b.url || '').trim();
  if (aUrl || bUrl) return Boolean(aUrl && bUrl && aUrl === bUrl);
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
  if (!isOpportunityValue(opp)) return null;
  const stored = readMutableImports(token);
  if (!stored.ok) return null;
  const existing = stored.list;
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
  const stored = readMutableImports(token);
  if (!stored.ok) return false;
  const existing = stored.list;
  const next = existing.filter((c) => c.id !== id);
  if (next.length === existing.length) return true;
  return writeLocalStorageJSON(STORAGE_KEY, next.length > 0 ? next : null, token);
}


export type CustomImportUpdateFailureReason =
  | 'owner_changed'
  | 'changed'
  | 'missing'
  | 'identity_mismatch'
  | 'storage_failed';

export type CustomImportUpdateResult =
  | { ok: true; entry: CustomImport }
  | { ok: false; reason: CustomImportUpdateFailureReason };

function isOpportunityValue(value: unknown): value is ImportedOpportunity {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const opp = value as Record<string, unknown>;
  if (!['source', 'title', 'description_raw'].every((key) => typeof opp[key] === 'string')) return false;
  if (!['source_url', 'url'].every((key) => opp[key] === undefined || typeof opp[key] === 'string')) return false;
  if (!['organization', 'deadline', 'posted_date', 'location', 'raw_html'].every((key) =>
    opp[key] === undefined || opp[key] === null || typeof opp[key] === 'string')) return false;
  return opp.extra_fields === undefined || Boolean(opp.extra_fields && typeof opp.extra_fields === 'object' && !Array.isArray(opp.extra_fields));
}

function isImportEntry(value: unknown): value is CustomImport {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
  const entry = value as Partial<CustomImport>;
  return typeof entry.id === 'string' && typeof entry.imported_at === 'string'
    && (entry.updated_at === undefined || typeof entry.updated_at === 'string')
    && isOpportunityValue(entry.opportunity);
}

// Compare JSON storage values, including unknown metadata, independently of
// object-key order. Array order and every retained value remain significant.
function snapshotValue(value: unknown): string {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(snapshotValue).join(',')}]`;
  return `{${Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, child]) => `${JSON.stringify(key)}:${snapshotValue(child)}`).join(',')}}`;
}

function sameImportSource(a: ImportedOpportunity, b: ImportedOpportunity): boolean {
  if (typeof a.source !== 'string' || !a.source || a.source !== b.source) return false;
  if (![a.source_url, a.url, b.source_url, b.url].every((value) => value === undefined || typeof value === 'string')) return false;
  const aSource = (a.source_url ?? '').trim();
  const bSource = (b.source_url ?? '').trim();
  const aUrl = (a.url ?? '').trim();
  const bUrl = (b.url ?? '').trim();
  // A populated secondary address must not silently change while the primary
  // address stays the same. Missing redundant aliases can be filled in only
  // when the effective source address still identifies the same page.
  if ((aSource && bSource && aSource !== bSource) || (aUrl && bUrl && aUrl !== bUrl)) return false;
  if (aSource || aUrl || bSource || bUrl) {
    return Boolean((aSource || aUrl) && (bSource || bUrl) && (aSource || aUrl) === (bSource || bUrl));
  }
  return isSameOpportunity(a, b);
}

type UpdateRead =
  | { ok: true; list: CustomImport[]; index: number }
  | { ok: false; reason: CustomImportUpdateFailureReason };

type MutableImportRead =
  | { ok: true; list: CustomImport[] }
  | { ok: false; reason: CustomImportUpdateFailureReason };

function readMutableImports(token: OwnerToken): MutableImportRead {
  if (!isOwnerTokenValid(token, token.uid)) return { ok: false, reason: 'owner_changed' };
  const stored = readUserScopedEntry(STORAGE_KEY);
  if (!isOwnerTokenValid(token, token.uid)) return { ok: false, reason: 'owner_changed' };
  if (stored.status === 'unavailable') {
    return { ok: false, reason: stored.reason === 'storage-error' ? 'storage_failed' : 'owner_changed' };
  }
  if (stored.status === 'absent') return { ok: true, list: [] };
  let list: unknown;
  try { list = JSON.parse(stored.value); } catch { return { ok: false, reason: 'storage_failed' }; }
  if (!Array.isArray(list) || !list.every(isImportEntry)) return { ok: false, reason: 'storage_failed' };
  return { ok: true, list };
}

function readUpdateTarget(expected: CustomImport, token: OwnerToken): UpdateRead {
  // Never inspect the new owner's entries on behalf of a stale intent.
  const stored = readMutableImports(token);
  if (!stored.ok) return stored;
  const { list } = stored;
  const matches = list.flatMap((entry, index) => entry.id === expected.id ? [index] : []);
  if (!matches.length) return { ok: false, reason: 'missing' };
  if (matches.length !== 1) return { ok: false, reason: 'changed' };
  const index = matches[0];
  if (snapshotValue(list[index]) !== snapshotValue(expected)) return { ok: false, reason: 'changed' };
  return { ok: true, list, index };
}

/** Replace one explicitly reviewed import, never refresh the expected snapshot.
 * Capture the owner token and deep-copy the COMPLETE old entry when review is
 * opened. Confirmation must pass those same snapshots; it may not recapture
 * the latest entry to make a stale review pass. All failure paths leave the
 * candidate with the caller and perform no compensating deletion/rollback.
 *
 * This synchronous check is not an atomic cross-tab localStorage transaction.
 * We re-read before writing, preserving intervening changes to other entries;
 * the browser still has no compare-and-swap for a write by an uncoordinated tab
 * between the final read and setItem. See docs/custom_import_updates.md.
 */
export function updateCustomImport(
  opp: ImportedOpportunity, expected: CustomImport, token: OwnerToken,
): CustomImportUpdateResult {
  const origin = { ...token };
  if (!isOwnerTokenValid(origin, origin.uid)) return { ok: false, reason: 'owner_changed' };
  let candidate: ImportedOpportunity;
  let reviewed: CustomImport;
  try {
    // Freeze the caller's values for this synchronous attempt and reject values
    // that JSON storage cannot represent; do not return a mutable cache object.
    candidate = JSON.parse(JSON.stringify(opp));
    reviewed = JSON.parse(JSON.stringify(expected));
  } catch { return { ok: false, reason: 'storage_failed' }; }
  if (!isImportEntry(reviewed) || !isOpportunityValue(candidate)) {
    return { ok: false, reason: 'storage_failed' };
  }
  const first = readUpdateTarget(reviewed, origin);
  if (!first.ok) return first;
  if (!sameImportSource(first.list[first.index].opportunity, candidate)) {
    return { ok: false, reason: 'identity_mismatch' };
  }
  // The second authoritative read compares the SAME reviewed entry, and uses
  // the latest surrounding list so an independently added item is not dropped.
  const current = readUpdateTarget(reviewed, origin);
  if (!current.ok) return current;
  const entry: CustomImport = {
    ...current.list[current.index], opportunity: candidate, updated_at: new Date().toISOString(),
  };
  const next = current.list.map((value, index) => index === current.index ? entry : value);
  const wrote = writeLocalStorageJSON(STORAGE_KEY, next, origin);
  if (!isOwnerTokenValid(origin, origin.uid)) return { ok: false, reason: 'owner_changed' };
  if (!wrote) return { ok: false, reason: 'storage_failed' };
  // A synchronous storage subscriber may have removed/replaced the entry
  // after the writer's own byte-level readback. Never claim our draft is saved
  // unless that same complete entry is still present; never roll back theirs.
  const persisted = readUpdateTarget(entry, origin);
  return persisted.ok ? { ok: true, entry } : persisted;
}
