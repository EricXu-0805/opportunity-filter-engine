import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { USER_SCOPED_KEYS, USER_SCOPED_PREFIXES } from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

// Static contract, A5: every USER_SCOPED_KEYS/USER_SCOPED_PREFIXES value
// carries no owner tag of its own — the identity-owner marker + readiness
// barrier is the ONLY thing standing between one account's data and the
// next's. A raw localStorage.getItem/setItem/removeItem call that bypasses
// readUserScopedRaw/writeUserScopedRaw/removeUserScopedRaw (or the
// use-local-storage-json.ts wrapper built on top of them) re-introduces
// that cross-account leak/clobber risk, one call site at a time, with
// nothing to catch a NEW offender except this test.
//
// This is a regex heuristic, not a full AST proof (matching
// profile-sync.contract.test.ts's own precedent), but it is
// ARGUMENT-precise, not just "does this file mention the key somewhere":
// for every raw localStorage.getItem/setItem/removeItem call, it resolves
// the call's first argument — either a direct `STORAGE_KEYS.NAME` or a
// local const alias declared as `const X = STORAGE_KEYS.NAME` earlier in
// the same file — and only flags it if THAT resolves to a tracked name.
// A file that legitimately raw-touches a DIFFERENT, non-tracked key (a
// device/session-scoped one, or a dead pre-migration key name) right next
// to a correctly-gated read of a tracked one is not a false positive here.

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

// The gateway itself. identity-owner.ts implements the marker/sweep and the
// readUserScopedRaw/writeUserScopedRaw/removeUserScopedRaw primitives;
// use-local-storage-json.ts wraps them for React-friendly reads. Neither can
// go through its own gate to implement it.
const GATEWAY_FILES = new Set([
  'lib/identity-owner.ts',
  'lib/use-local-storage-json.ts',
]);

// Explicit, reviewed exceptions — each with its own justification. Anything
// NOT listed here that both references a tracked key AND raw-touches
// localStorage is a genuine, unreviewed bypass.
const ALLOWED_RAW_TOUCH: Record<string, string> = {
  'components/TailorModal.tsx':
    'TAILOR_DRAFT_PREFIX only — the owner uid is embedded directly IN the key ' +
    'name (draftStorageKey: prefix + ownerScopeKey + ":" + opportunityId), so ' +
    'a stale write structurally lands under a DIFFERENT key than any other ' +
    "identity's, not the same fixed-name slot the gate protects. See the file's " +
    'own C1-R2B comment block. The remaining question — whether ownerScopeKey ' +
    'itself needs an isLocalOwnerReadyNow()-style blocking check during a ' +
    'transition — is tracked separately (Tail1-3), not a raw-bypass gap.',
};

function trackedNames(values: readonly string[]): string[] {
  return Object.entries(STORAGE_KEYS)
    .filter(([, value]) => (values as readonly string[]).includes(value))
    .map(([name]) => name);
}

const TRACKED_KEY_NAMES = trackedNames(USER_SCOPED_KEYS);
const TRACKED_PREFIX_NAMES = trackedNames(USER_SCOPED_PREFIXES);
const ALL_TRACKED_NAMES = [...TRACKED_KEY_NAMES, ...TRACKED_PREFIX_NAMES];

const RAW_CALL_RE = /(?:window\.)?localStorage\.(getItem|setItem|removeItem)\s*\(/;
const ALIAS_DECL_RE = /(?:const|let)\s+(\w+)\s*(?::[^=]+)?=\s*STORAGE_KEYS\.(\w+)\b/g;
const RAW_CALL_ARG_RE = /(?:window\.)?localStorage\.(?:getItem|setItem|removeItem)\s*\(\s*([^,)\s]+)/g;

/** Aliases declared in `src` as `const X = STORAGE_KEYS.NAME` (or `let`,
 *  optionally typed) — resolves one level of local-const indirection so a
 *  file that does `const LS_KEY = STORAGE_KEYS.EMAIL_HINT;` then
 *  `localStorage.getItem(LS_KEY)` is still caught by name, not just by a
 *  direct `STORAGE_KEYS.EMAIL_HINT` argument. */
function resolveAliases(src: string): Map<string, string> {
  const aliases = new Map<string, string>();
  for (const m of src.matchAll(ALIAS_DECL_RE)) aliases.set(m[1], m[2]);
  return aliases;
}

/** Every tracked STORAGE_KEYS name (direct or via a resolved local alias)
 *  that some raw localStorage call's first argument resolves to. */
function trackedNamesRawlyTouched(src: string): string[] {
  const aliases = resolveAliases(src);
  const touched = new Set<string>();
  for (const m of src.matchAll(RAW_CALL_ARG_RE)) {
    const arg = m[1];
    const direct = /^STORAGE_KEYS\.(\w+)$/.exec(arg);
    const name = direct ? direct[1] : aliases.get(arg);
    if (name && ALL_TRACKED_NAMES.includes(name)) touched.add(name);
  }
  return Array.from(touched);
}

describe('USER_SCOPED_KEYS/PREFIXES — static raw-bypass contract (A5)', () => {
  it('every tracked key/prefix has at least one registered STORAGE_KEYS name (sanity: the reverse-lookup below is not silently empty)', () => {
    expect(TRACKED_KEY_NAMES.length).toBe(USER_SCOPED_KEYS.length);
    expect(TRACKED_PREFIX_NAMES.length).toBe(USER_SCOPED_PREFIXES.length);
  });

  it('no non-gateway, non-allowlisted source file passes a tracked STORAGE_KEYS name (direct or via a local alias) as the key argument to a raw localStorage.getItem/setItem/removeItem call', () => {
    const offenders: string[] = [];
    for (const file of SOURCE_FILES) {
      const name = rel(file);
      if (GATEWAY_FILES.has(name) || ALLOWED_RAW_TOUCH[name]) continue;
      const src = readFileSync(file, 'utf8');
      const touchedNames = trackedNamesRawlyTouched(src);
      if (touchedNames.length > 0) offenders.push(`${name}: ${touchedNames.join(', ')}`);
    }
    expect(offenders).toEqual([]);
  });

  it('the allowlist names only files that genuinely still raw-touch localStorage — a stale entry (site since migrated) is a false sense of coverage, not a passing test', () => {
    const staleEntries: string[] = [];
    for (const [name, _reason] of Object.entries(ALLOWED_RAW_TOUCH)) {
      const file = SOURCE_FILES.find((f) => rel(f) === name);
      expect(file, `allowlisted file ${name} does not exist`).toBeDefined();
      const src = readFileSync(file!, 'utf8');
      if (!RAW_CALL_RE.test(src)) staleEntries.push(name);
    }
    expect(staleEntries).toEqual([]);
  });

  it('the gateway list names only files that actually implement raw localStorage access — a stale entry would hide a real offender behind an unnecessary exemption', () => {
    const staleEntries: string[] = [];
    for (const name of GATEWAY_FILES) {
      const file = SOURCE_FILES.find((f) => rel(f) === name);
      expect(file, `gateway file ${name} does not exist`).toBeDefined();
      const src = readFileSync(file!, 'utf8');
      if (!RAW_CALL_RE.test(src)) staleEntries.push(name);
    }
    expect(staleEntries).toEqual([]);
  });
});
