'use client';

import { useSyncExternalStore } from 'react';
import {
  readLocalStorageJSON,
  useLocalStorageJSON,
  writeLocalStorageJSON,
} from './use-local-storage-json';
import { captureOwnerToken, hasSerializationBackend, isOwnerTokenValid, isTokenOwnerStillCurrent,
  onLocalOwnerStateChange, PRIVATE_STORAGE_LOCK, readUserScopedEntry, type OwnerToken } from './identity-owner';
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

export type CustomImportWriteFailureReason =
  | 'owner_changed' | 'changed' | 'missing' | 'identity_mismatch'
  | 'storage_failed' | 'storage_damaged' | 'coordination_unavailable' | 'lock_timeout';
export type CustomImportUpdateFailureReason = CustomImportWriteFailureReason;
export type CustomImportFailure = { ok: false; reason: CustomImportWriteFailureReason };
export type CustomImportUpdateResult = { ok: true; entry: CustomImport } | CustomImportFailure;
export type CustomImportWriteResult = { ok: true } | CustomImportFailure;
export type CustomImportStorageState =
  | { status: 'ready'; entries: CustomImport[] }
  | { status: 'damaged'; entries: CustomImport[] }
  | { status: 'unavailable'; entries: CustomImport[]; reason: CustomImportWriteFailureReason };
export const CUSTOM_IMPORT_LOCK_TIMEOUT_MS = 10_000;

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

function authorityFailure(token: OwnerToken): CustomImportFailure | null {
  if (!isTokenOwnerStillCurrent(token)) return { ok: false, reason: 'owner_changed' };
  if (!hasSerializationBackend()) return { ok: false, reason: 'coordination_unavailable' };
  if (!isOwnerTokenValid(token, token.uid)) return { ok: false, reason: 'owner_changed' };
  return null;
}

type StorageSnapshot =
  | { status: 'ready' | 'damaged'; entries: CustomImport[]; raw: string | null }
  | { status: 'unavailable'; entries: CustomImport[]; reason: CustomImportWriteFailureReason };

function storageSnapshot(token: OwnerToken): StorageSnapshot {
  const before = authorityFailure(token);
  if (before) return { status: 'unavailable', entries: EMPTY_IMPORTS, reason: before.reason };
  const stored = readUserScopedEntry(STORAGE_KEY);
  const after = authorityFailure(token);
  if (after) return { status: 'unavailable', entries: EMPTY_IMPORTS, reason: after.reason };
  if (stored.status === 'unavailable') return { status: 'unavailable', entries: EMPTY_IMPORTS,
    reason: stored.reason === 'storage-error' ? 'storage_failed' : 'owner_changed' };
  if (stored.status === 'absent') return { status: 'ready', entries: EMPTY_IMPORTS, raw: null };
  let value: unknown;
  try { value = JSON.parse(stored.value); } catch {
    return { status: 'damaged', entries: EMPTY_IMPORTS, raw: stored.value };
  }
  const entries = displayImports(value);
  const valid = Array.isArray(value) && value.every(isImportEntry)
    && new Set(entries.map(entry => entry.id)).size === entries.length;
  return { status: valid ? 'ready' : 'damaged', entries, raw: stored.value };
}

let stateCache: { owner: string; raw: string | null; status: string; state: CustomImportStorageState } | null = null;
const SERVER_STATE: CustomImportStorageState = { status: 'unavailable', entries: EMPTY_IMPORTS, reason: 'coordination_unavailable' };

/** Safe display status, without exposing the raw damaged value on normal reads. */
export function readCustomImportStorageState(token: OwnerToken): CustomImportStorageState {
  const origin = { ...token };
  const value = storageSnapshot(origin);
  const owner = JSON.stringify(origin);
  const raw = value.status === 'unavailable' ? null : value.raw;
  const status = value.status === 'unavailable' ? value.reason : value.status;
  if (stateCache?.owner === owner && stateCache.raw === raw && stateCache.status === status) return stateCache.state;
  const state: CustomImportStorageState = value.status === 'unavailable'
    ? { status: 'unavailable', entries: EMPTY_IMPORTS, reason: value.reason }
    : { status: value.status, entries: value.entries };
  stateCache = { owner, raw, status, state };
  return state;
}
function subscribeStorageState(callback: () => void): () => void {
  const stopOwner = onLocalOwnerStateChange(callback);
  window.addEventListener('storage', callback);
  return () => { stopOwner(); window.removeEventListener('storage', callback); };
}
function currentStorageState(): CustomImportStorageState { return readCustomImportStorageState(captureOwnerToken()); }
export function useCustomImportStorageState(): CustomImportStorageState {
  return useSyncExternalStore(subscribeStorageState, currentStorageState, () => SERVER_STATE);
}

function readMutableImports(token: OwnerToken): MutableImportRead {
  const value = storageSnapshot(token);
  if (value.status === 'unavailable') return { ok: false, reason: value.reason };
  if (value.status === 'damaged') return { ok: false, reason: 'storage_damaged' };
  return { ok: true, list: value.entries };
}

/** One cooperative transaction shared with account transitions and other
 * private writers. The callback is synchronous; no network or identity await
 * may be added inside it. Only pending acquisition can time out. */
async function coordinated<T extends { ok: boolean }>(origin: OwnerToken, mutate: () => T): Promise<T | CustomImportFailure> {
  const initial = authorityFailure(origin);
  if (initial) return initial;
  const controller = new AbortController();
  let expired = false;
  let acquired = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const deadline = new Promise<CustomImportFailure>((resolve) => {
    timer = setTimeout(() => {
      if (acquired) return;
      expired = true;
      resolve({ ok: false, reason: 'lock_timeout' });
      controller.abort();
    }, CUSTOM_IMPORT_LOCK_TIMEOUT_MS);
  });
  try {
    const operation = navigator.locks.request(PRIVATE_STORAGE_LOCK, { mode: 'exclusive', signal: controller.signal }, () => {
      // Also defend against an implementation/mock that ignores abort.
      if (expired) return { ok: false, reason: 'lock_timeout' } as const;
      acquired = true;
      clearTimeout(timer);
      const before = authorityFailure(origin);
      if (before) return before;
      const result = mutate();
      return authorityFailure(origin) ?? result;
    });
    const result = await Promise.race([operation, deadline]);
    return authorityFailure(origin) ?? result;
  } catch {
    return authorityFailure(origin) ?? { ok: false, reason: expired ? 'lock_timeout' : 'storage_failed' };
  } finally { clearTimeout(timer); }
}

/** Original intent token and candidate are frozen before waiting for the lock. */
export async function addCustomImport(opp: ImportedOpportunity, token: OwnerToken): Promise<CustomImportUpdateResult> {
  const origin = { ...token };
  let candidate: ImportedOpportunity;
  try { candidate = JSON.parse(JSON.stringify(opp)); } catch { return { ok: false, reason: 'storage_failed' }; }
  if (!isOpportunityValue(candidate)) return { ok: false, reason: 'storage_failed' };
  return coordinated(origin, () => {
    const current = readMutableImports(origin);
    if (!current.ok) return current;
    const existing = findExistingImport(candidate, current.list);
    if (existing) return { ok: true, entry: existing } as const;
    const entry: CustomImport = { id: generateId(), imported_at: new Date().toISOString(), opportunity: candidate };
    if (!writeLocalStorageJSON(STORAGE_KEY, [entry, ...current.list], origin)) return { ok: false, reason: 'storage_failed' } as const;
    const persisted = readUpdateTarget(entry, origin);
    return persisted.ok ? { ok: true, entry } as const : persisted;
  });
}

export async function removeCustomImport(id: string, token: OwnerToken): Promise<CustomImportWriteResult> {
  const origin = { ...token };
  if (typeof id !== 'string') return { ok: false, reason: 'storage_failed' };
  return coordinated(origin, () => {
    const current = readMutableImports(origin);
    if (!current.ok) return current;
    const next = current.list.filter(entry => entry.id !== id);
    if (next.length === current.list.length) return { ok: true } as const;
    if (!writeLocalStorageJSON(STORAGE_KEY, next.length ? next : null, origin)) return { ok: false, reason: 'storage_failed' } as const;
    const persisted = readMutableImports(origin);
    if (!persisted.ok) return persisted;
    return persisted.list.some(entry => entry.id === id) ? { ok: false, reason: 'changed' } as const : { ok: true } as const;
  });
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

/** Replace only the complete reviewed snapshot, never recapture the expected
 * entry or owner after waiting. All current import writers and owner changes
 * share one exclusive lock. Old builds/direct storage writes remain outside
 * this cooperative protocol; no failure attempts a destructive rollback. */
export async function updateCustomImport(
  opp: ImportedOpportunity, expected: CustomImport, token: OwnerToken,
): Promise<CustomImportUpdateResult> {
  const origin = { ...token };
  let candidate: ImportedOpportunity;
  let reviewed: CustomImport;
  try {
    candidate = JSON.parse(JSON.stringify(opp));
    reviewed = JSON.parse(JSON.stringify(expected));
  } catch { return { ok: false, reason: 'storage_failed' }; }
  if (!isImportEntry(reviewed) || !isOpportunityValue(candidate)) return { ok: false, reason: 'storage_failed' };
  return coordinated(origin, () => {
    const first = readUpdateTarget(reviewed, origin);
    if (!first.ok) return first;
    const current = readUpdateTarget(reviewed, origin);
    if (!current.ok) return current;
    if (!sameImportSource(current.list[current.index].opportunity, candidate)) return { ok: false, reason: 'identity_mismatch' } as const;
    const entry: CustomImport = {
      ...current.list[current.index], opportunity: candidate, updated_at: new Date().toISOString(),
    };
    const next = current.list.map((value, index) => index === current.index ? entry : value);
    if (!writeLocalStorageJSON(STORAGE_KEY, next, origin)) return { ok: false, reason: 'storage_failed' } as const;
    const persisted = readUpdateTarget(entry, origin);
    return persisted.ok ? { ok: true, entry } as const : persisted;
  });
}

/** Explicit recovery/export request. The caller retains this exact raw value
 * and token through confirmation; normal display never exposes damaged raw. */
export function captureCustomImportRecovery(token: OwnerToken): { ok: true; raw: string } | CustomImportFailure {
  const current = storageSnapshot({ ...token });
  if (current.status === 'unavailable') return { ok: false, reason: current.reason };
  if (current.status !== 'damaged' || current.raw === null) return { ok: false, reason: 'changed' };
  return { ok: true, raw: current.raw };
}

export async function resetCustomImports(expectedRaw: string, token: OwnerToken): Promise<CustomImportWriteResult> {
  const origin = { ...token };
  if (typeof expectedRaw !== 'string') return { ok: false, reason: 'storage_failed' };
  return coordinated(origin, () => {
    const current = storageSnapshot(origin);
    if (current.status === 'unavailable') return { ok: false, reason: current.reason };
    if (current.status !== 'damaged' || current.raw !== expectedRaw) return { ok: false, reason: 'changed' } as const;
    if (!writeLocalStorageJSON(STORAGE_KEY, [], origin)) return { ok: false, reason: 'storage_failed' } as const;
    const persisted = storageSnapshot(origin);
    if (persisted.status === 'unavailable') return { ok: false, reason: persisted.reason };
    if (persisted.status !== 'ready' || persisted.raw !== '[]') return { ok: false, reason: 'changed' } as const;
    return { ok: true } as const;
  });
}
