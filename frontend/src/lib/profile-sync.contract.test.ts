import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { CREATE_REQUIRED_KEYS, RESUME_BUNDLE } from './profile-sync';
import { DEFAULT_PROFILE } from '@/app/home/types';
import { STORAGE_KEYS } from './storage-keys';
import { USER_SCOPED_KEYS } from './identity-owner';

// Static contract for the profile row. These are the invariants that make
// "one screen's stale snapshot cannot overwrite another device's edit" a
// property of the CODEBASE rather than of whoever last touched a call site —
// a behavioural test can only cover the paths it happens to exercise.

const SRC = join(__dirname, '..');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) { out.push(...walk(full)); continue; }
    if (/\.(ts|tsx)$/.test(entry) && !/\.test\.(ts|tsx)$/.test(entry)) out.push(full);
  }
  return out;
}

const SOURCE_FILES = walk(SRC);
const rel = (f: string) => f.slice(SRC.length + 1);

describe('profile write path — static contract', () => {
  // The coordinator is the only module allowed to put a value in the profile
  // slot. Everything else reads it. A new screen that "just saves the profile
  // it has" is precisely the pre-CAS bug, so it fails here rather than in
  // production three devices later.
  const PROFILE_WRITERS = new Set(['lib/profile-sync.ts']);

  it('only the coordinator writes STORAGE_KEYS.PROFILE', () => {
    const offenders: string[] = [];
    for (const file of SOURCE_FILES) {
      const name = rel(file);
      if (PROFILE_WRITERS.has(name)) continue;
      const src = readFileSync(file, 'utf8');
      // write/remove through the guarded helpers, or a raw setItem on the key
      if (
        /write(LocalStorageJSON|UserScopedRaw)\(\s*STORAGE_KEYS\.PROFILE\b/.test(src)
        || /removeUserScopedRaw\(\s*STORAGE_KEYS\.PROFILE\b/.test(src)
        || new RegExp(`setItem\\(\\s*['"\`]${STORAGE_KEYS.PROFILE}['"\`]`).test(src)
      ) offenders.push(name);
    }
    expect(offenders).toEqual([]);
  });

  it('only the coordinator writes the sync envelope', () => {
    const offenders = SOURCE_FILES
      .filter((f) => !PROFILE_WRITERS.has(rel(f)))
      .filter((f) => /STORAGE_KEYS\.PROFILE_SYNC/.test(readFileSync(f, 'utf8')))
      // storage-keys declares it; identity-owner registers it for clearing
      .filter((f) => !['lib/storage-keys.ts', 'lib/identity-owner.ts'].includes(rel(f)))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it('only the service module calls the CAS RPC, and it is the PATCH one', () => {
    const callers = SOURCE_FILES
      .filter((f) => /commit_profile_patch_cas/.test(readFileSync(f, 'utf8')))
      .map(rel);
    expect(callers).toEqual(['lib/supabase.ts']);

    // There is no full-row sibling anywhere in the client either.
    const fullRow = SOURCE_FILES
      .filter((f) => /commit_profile_cas\b|commit_profile_full/.test(readFileSync(f, 'utf8')))
      .map(rel);
    expect(fullRow).toEqual([]);
  });

  it('nothing writes the profiles/profile_versions tables directly', () => {
    const offenders: string[] = [];
    for (const file of SOURCE_FILES) {
      const src = readFileSync(file, 'utf8');
      // .from('profiles') followed by a mutating verb anywhere in the chain
      for (const table of ['profiles', 'profile_versions']) {
        const re = new RegExp(`from\\(['"\`]${table}['"\`]\\)[\\s\\S]{0,120}?\\.(upsert|insert|update|delete)\\(`);
        if (re.test(src)) offenders.push(`${rel(file)}:${table}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it('every profile edit goes through the DURABLE journal, never a bare in-memory mark', () => {
    // An edit that only reaches the in-memory map is invisible to other tabs
    // and gone after a reload. recordProfileIntent writes the journal first;
    // markProfileFieldsDirty is its private cache half and is not exported.
    const offenders = SOURCE_FILES
      .filter((f) => rel(f) !== 'lib/profile-sync.ts')
      .filter((f) => /\bmarkProfileFieldsDirty\s*\(/.test(readFileSync(f, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
    expect(/export function markProfileFieldsDirty/.test(
      readFileSync(join(SRC, 'lib/profile-sync.ts'), 'utf8'),
    )).toBe(false);
  });

  it('only the coordinator touches the journal', () => {
    const offenders = SOURCE_FILES
      .filter((f) => !['lib/profile-sync.ts', 'lib/profile-journal.ts'].includes(rel(f)))
      .filter((f) => /from '\.\/profile-journal'|from '@\/lib\/profile-journal'/.test(readFileSync(f, 'utf8')))
      .map(rel);
    expect(offenders).toEqual([]);
  });

  it('only the coordinator is allowed to build a CAS intent', () => {
    const callers = SOURCE_FILES
      .filter((f) => rel(f) !== 'lib/supabase.ts')
      .filter((f) => /\bcommitProfilePatch\s*\(/.test(readFileSync(f, 'utf8')))
      .map(rel);
    expect(callers).toEqual(['lib/profile-sync.ts']);
  });
});

describe('profile write path — shape contracts', () => {
  it('DEFAULT_PROFILE carries every key the server requires for a create', () => {
    // Migration 027 refuses an expected_revision=0 patch that is missing any
    // of these, because a create BECOMES the stored document. If the home
    // form's default ever stopped carrying one, every brand-new account would
    // fail its first save with a server error instead of here.
    for (const key of CREATE_REQUIRED_KEYS) {
      expect(Object.prototype.hasOwnProperty.call(DEFAULT_PROFILE, key)).toBe(true);
      expect((DEFAULT_PROFILE as unknown as Record<string, unknown>)[key]).not.toBeUndefined();
    }
  });

  it('the résumé bundle is exactly the fields a résumé produces', () => {
    expect([...RESUME_BUNDLE].sort()).toEqual(['coursework', 'resume_text']);
  });

  it('the sync envelope is cleared on an account switch', () => {
    // It holds a revision and an unsent copy of the profile — one account's
    // must never be presented as another's.
    expect(USER_SCOPED_KEYS).toContain(STORAGE_KEYS.PROFILE_SYNC);
  });
});
