import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { ProfileData } from './types';
import type { LoadedProfile, ProfilePatchIntent, ProfilePatchOutcome } from './supabase';
import type { ProfileConflict } from './profile-sync';

// The service layer is faked; everything else — identity-owner, the guarded
// storage helpers, jsdom's real localStorage — is the production code.
const loadProfileMock = vi.fn<() => Promise<LoadedProfile>>();
const commitMock = vi.fn<(i: ProfilePatchIntent) => Promise<ProfilePatchOutcome>>();
vi.mock('./supabase', () => ({
  loadProfile: () => loadProfileMock(),
  commitProfilePatch: (intent: ProfilePatchIntent) => commitMock(intent),
}));

import {
  advanceOwnerEpoch,
  captureOwnerToken,
  isOwnerScopedLoadError,
  isOwnerTokenValid,
  isTokenOwnerStillCurrent,
  OwnerScopedLoadError,
  syncLocalIdentityOwner,
  writeUserScopedRaw,
  type OwnerToken,
} from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';
import {
  appendJournalOp,
  effectiveOpBase,
  getJournalLineageId,
  readOutstandingOps,
  readRebaseReceipts,
  resetJournalLaneForTests,
  startDocumentForTests,
  type JournalOp,
} from './profile-journal';
import {
  flushPendingProfileWrite,
  getDirtyProfileKeys,
  HOME_FORM_WRITER,
  hydrateProfile,
  recordProfileIntent,
  markSkillAdditions,
  markSkillsReplaced,
  readProfileSyncEnvelope,
  makeProfileViewSnapshot,
  withRenderedProfile,
  makeConflictPrompt,
  readProfileView,
  resetProfileDirtyLedger,
  commitProfileAction,
  resolveProfileConflict,
  readCurrentConflicts,
  planKeysFromJournalForTests,
  refreshConflictQuestion,
  stageProfilePatch,
  type ProfileSaveResult,
  type ProfileViewSnapshot,
} from './profile-sync';

const UID = 'sync-u1';

/**
 * Trust comes from the production guard, never from a shape: this asserts the
 * failure IS a real scoped capability and narrows it, so `ownerToken` below is
 * only ever read off a genuine one.
 */
function scopedCapability(err: unknown): OwnerScopedLoadError {
  expect(isOwnerScopedLoadError(err),
    'the failure is a real scoped capability, not an object shaped like one')
    .toBe(true);
  return err as OwnerScopedLoadError;
}

/** For NEGATIVE cases only: what an object CLAIMS, without trusting it. */
function claimedOwnerToken(err: unknown): unknown {
  return (err as { ownerToken?: unknown } | null | undefined)?.ownerToken;
}

function caught(p: Promise<unknown>): Promise<unknown> {
  return p.then(() => null, (e) => e);
}


const FULL: ProfileData = {
  institution: 'UIUC',
  home_school: 'uiuc',
  college: 'Grainger',
  major: 'CS',
  grade: 'Junior',
  is_international: false,
  research_interests: 'robotics',
  skills: [{ name: 'Python', level: 'experienced' }],
  search_weight: 50,
};

function cloud(profile: ProfileData, revision: number): LoadedProfile {
  return { source: 'cloud', profile: profile as unknown as Record<string, unknown>, revision, token: captureOwnerToken() };
}
function absent(): LoadedProfile {
  return { source: 'cloud-absent', profile: null, revision: 0, token: captureOwnerToken() };
}
function localOnly(profile: ProfileData | null): LoadedProfile {
  return { source: 'local-only', profile: profile as unknown as Record<string, unknown> | null, revision: 0, token: captureOwnerToken() };
}
/** A view a surface would have accepted showing `profile` at `revision`. The
 *  base and the rendered document are the same here because these tests are
 *  about the pairing, not about defaults. */
/**
 * The published question and the screen it was answered on, as the one
 * capability the resolver now takes. Each of these tests already described a
 * person looking at `observed` on view `view`; this states that directly
 * instead of handing the resolver two values it had to trust were related.
 */
function answerOn(
  view: ProfileViewSnapshot,
  rendered: readonly ProfileConflict[],
  choice: 'local' | 'cloud',
  observed: ProfileData,
) {
  const actionView = withRenderedProfile(view, observed);
  return { prompt: makeConflictPrompt(actionView, rendered), actionView, choice };
}

function viewOf(profile: ProfileData, revision: number, owner: OwnerToken) {
  return makeProfileViewSnapshot({
    baseProfile: profile,
    renderedProfile: profile,
    revision,
    token: owner,
    identityGeneration: owner.epoch,
    source: 'hydration',
  });
}

/** A CAS-faithful server: it REFUSES anything whose expected revision is not
 *  the row's. A fake that answers `saved` to every request cannot tell a
 *  correctly rebased send apart from one aimed at a revision that no longer
 *  exists — which is the entire failure being tested. */
function casServer(initial: ProfileData, revision: number) {
  let row = { ...initial } as Record<string, unknown>;
  let rev = revision;
  const seen: { expected: number; patch: Record<string, unknown> }[] = [];
  return {
    get row() { return row; },
    get rev() { return rev; },
    seen,
    handle(intent: { expectedRevision: number; patch: Record<string, unknown> }) {
      seen.push({ expected: intent.expectedRevision, patch: { ...intent.patch } });
      if (intent.expectedRevision !== rev) {
        return { status: 'conflict' as const, revision: rev, profile: { ...row } };
      }
      row = { ...row, ...intent.patch };
      rev += 1;
      return { status: 'saved' as const, revision: rev, profile: { ...row } };
    },
  };
}

/** The public conflict API takes ONE immutable answer. These tests answer the
 *  question the coordinator itself just published, which is exactly what the
 *  UI does. */
function answerConflict(
  keys: readonly string[],
  choice: 'local' | 'cloud',
  owner: OwnerToken,
  observed?: ProfileData,
  rendered?: readonly ProfileConflict[],
) {
  // The question the coordinator itself publishes — exactly what the UI
  // renders and hands back.
  const shown = rendered ?? readCurrentConflicts(keys, owner);
  return resolveProfileConflict(answerOn(
      viewOf((observed ?? FULL), readProfileSyncEnvelope()?.confirmed?.revision ?? 0, owner),
      shown,
      choice,
      observed ?? (readProfileSyncEnvelope()?.pending?.desiredProfile as ProfileData) ?? FULL,
    ));
}

function saved(profile: ProfileData, revision: number): ProfilePatchOutcome {
  return { status: 'saved', revision, profile: profile as unknown as Record<string, unknown> };
}
function conflict(profile: ProfileData, revision: number): ProfilePatchOutcome {
  return { status: 'conflict', revision, profile: profile as unknown as Record<string, unknown> };
}

function rawMirror(): ProfileData | null {
  const raw = localStorage.getItem(STORAGE_KEYS.PROFILE);
  return raw ? JSON.parse(raw) as ProfileData : null;
}

/** getDirtyProfileKeys returns a typed result now — a journal it cannot read
 *  must stop the caller, not degrade to a partial list. */
function dirtyKeys(token: Parameters<typeof getDirtyProfileKeys>[0], writer?: string) {
  const r = getDirtyProfileKeys(token, writer);
  if (!r.ok) throw new Error(`journal unreadable: ${r.reason}`);
  return r.value;
}

const tick = () => new Promise((r) => { setTimeout(r, 0); });

async function seedOwner(uid = UID) {
  advanceOwnerEpoch(uid);
  await syncLocalIdentityOwner(uid);
}

// jsdom has no Web Locks; every browser this ships to does. Installing a
// serial fake keeps these tests about the coordinator's logic rather than
// about the environment gap — the "no lock manager" behaviour has its own
// test in profile-journal.test.ts.
beforeEach(async () => {
  let chain: Promise<unknown> = Promise.resolve();
  Object.defineProperty(navigator, 'locks', {
    configurable: true,
    value: {
      request: (_name: string, _opts: unknown, fn: () => Promise<unknown>) => {
        const run = chain.then(() => fn());
        chain = run.then(() => undefined, () => undefined);
        return run;
      },
    },
  });
  localStorage.clear();
  // Every test starts as a freshly opened tab: no inherited session state, no
  // navigation kind left over from the test before it. Without this, a test
  // that arranges a reload leaves the NEXT one hydrating as a reload too, and
  // "these two documents got different lineages" can come out true for
  // reasons the test never set up.
  resetJournalLaneForTests();
  loadProfileMock.mockReset();
  commitMock.mockReset();
  resetProfileDirtyLedger();
  advanceOwnerEpoch(null);
  await seedOwner();
});

describe('hydrate', () => {
  it('records the revision and mirrors the row for legacy readers', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    const h = await hydrateProfile();
    expect(h.revision).toBe(7);
    expect(h.source).toBe('cloud');
    expect(readProfileSyncEnvelope()?.confirmed).toEqual({ revision: 7, profile: FULL });
    expect(rawMirror()).toEqual(FULL);
  });

  it('shows unsent edits on top of the cloud row, not the cloud row alone', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    const token = captureOwnerToken();
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);

    // A reload: the server still says CS, but the user's unsent ECE is theirs.
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    const h = await hydrateProfile();
    expect(h.profile?.major).toBe('ECE');
    expect(h.hasPending).toBe(true);
    expect(rawMirror()?.major).toBe('ECE');
  });

  it('does NOT blindly rebase a pending onto a newer row — a same-key remote change locks', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    const token = captureOwnerToken();
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);

    // Another device set major to Physics while this one was offline.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 9));
    const h = await hydrateProfile();
    expect(h.conflictKeys).toEqual(['major']);

    // ... and a plain retry must NOT push ECE over it.
    commitMock.mockClear();
    const result = await flushPendingProfileWrite(captureOwnerToken());
    expect(commitMock).not.toHaveBeenCalled();
    expect(result.status).toBe('conflict');
  });

  it('quarantines the raw mirror when the row has disappeared', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    expect(rawMirror()).not.toBeNull();

    loadProfileMock.mockResolvedValue(absent());
    const h = await hydrateProfile();
    // /results, /favorites and /compare all read this slot; leaving the old
    // row there means matching against a profile that no longer exists.
    expect(rawMirror()).toBeNull();
    expect(h.quarantineFailed).toBe(false);
    expect(readProfileSyncEnvelope()?.confirmed).toBeNull();
  });

  it('a pre-CAS mirror that disagrees with the cloud is locked, not uploaded or dropped', async () => {
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ ...FULL, major: 'LocalOnly' }));
    loadProfileMock.mockResolvedValue(cloud(FULL, 3));
    const h = await hydrateProfile();
    expect(h.conflictKeys).toEqual(['major']);
    commitMock.mockClear();
    const result = await flushPendingProfileWrite(captureOwnerToken());
    expect(commitMock).not.toHaveBeenCalled();
    expect(result.status).toBe('conflict');
  });
});

describe('staging', () => {
  it('sends ONLY the touched keys, at the revision it was read at', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE' }, 8));
    const token = captureOwnerToken();
    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);

    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(7);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'ECE' });
    expect(result.status).toBe('saved');
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(8);
    expect(readProfileSyncEnvelope()?.pending).toBeNull();
  });

  it('refuses to patch when no revision has ever been confirmed and the row is absent', async () => {
    loadProfileMock.mockResolvedValue(absent());
    const result = await stageProfilePatch(FULL, ['include_cross_school'], captureOwnerToken());
    // The cloud says there is no row; a one-field writer may not create one.
    expect(result.status).toBe('staged-local');
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('a fresh account can stage its campus with ZERO requests, then the complete create carries it', async () => {
    loadProfileMock.mockResolvedValue(absent());
    await hydrateProfile();
    const token = captureOwnerToken();

    const staged = await stageProfilePatch(
      { home_school: 'mit' } as unknown as ProfileData, ['home_school'], token,
    );
    expect(staged.status).toBe('staged-local');
    expect(commitMock).not.toHaveBeenCalled();
    expect(readProfileSyncEnvelope()?.pending?.dirtyKeys).toEqual(['home_school']);
    expect(rawMirror()?.home_school).toBe('mit');

    // The home form now saves a complete profile: ONE request, carrying the
    // campus the tour staged.
    commitMock.mockResolvedValue(saved({ ...FULL, home_school: 'mit' }, 1));
    const created = await stageProfilePatch(
      { ...FULL, home_school: 'mit' }, ['major'], token, { allowCreate: true },
    );
    expect(created.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(0);
    expect(commitMock.mock.calls[0][0].patch.home_school).toBe('mit');
    expect(commitMock.mock.calls[0][0].patch.college).toBe('Grainger');
  });

  it('refuses an incomplete create rather than letting the server reject it', async () => {
    loadProfileMock.mockResolvedValue(absent());
    await hydrateProfile();
    const partial = { college: 'Grainger', major: 'CS' } as unknown as ProfileData;
    const result = await stageProfilePatch(partial, ['major'], captureOwnerToken(), { allowCreate: true });
    expect(result.status).toBe('blocked');
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('local-only stages durably and never sends', async () => {
    loadProfileMock.mockResolvedValue(localOnly(null));
    await hydrateProfile();
    const result = await stageProfilePatch(
      { ...FULL, home_school: 'mit' }, ['home_school'], captureOwnerToken(),
    );
    expect(result.status).toBe('local-only');
    expect(commitMock).not.toHaveBeenCalled();
    expect(rawMirror()?.home_school).toBe('mit');
    expect(readProfileSyncEnvelope()?.pending).not.toBeNull();
  });
});

describe('conflicts', () => {
  it('rebases ONCE for a disjoint edit', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    // Another device changed `grade`; this one is changing `major`.
    const remote = { ...FULL, grade: 'Senior' };
    commitMock
      .mockResolvedValueOnce(conflict(remote, 8))
      .mockResolvedValueOnce(saved({ ...remote, major: 'ECE' }, 9));

    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], captureOwnerToken());
    expect(result.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(2);
    expect(commitMock.mock.calls[1][0].expectedRevision).toBe(8);
    expect(commitMock.mock.calls[1][0].patch).toEqual({ major: 'ECE' });
    // The other device's grade survived.
    expect(rawMirror()?.grade).toBe('Senior');
  });

  it('locks a same-key collision and stops auto-retrying it', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    commitMock.mockResolvedValue(conflict({ ...FULL, major: 'Physics' }, 8));

    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], captureOwnerToken());
    expect(result.status).toBe('conflict');
    expect((result as { conflictKeys: string[] }).conflictKeys).toEqual(['major']);
    expect(readProfileSyncEnvelope()?.pending?.lockedKeys).toEqual(['major']);

    // A plain retry must not send it again: with the base moved to the remote
    // value, an unlocked retry would look "safe" and overwrite the other
    // device.
    commitMock.mockClear();
    const retry = await flushPendingProfileWrite(captureOwnerToken());
    expect(commitMock).not.toHaveBeenCalled();
    expect(retry.status).toBe('conflict');
  });

  it('locks when the rebase budget runs out instead of punching through', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    // Disjoint every time, but the row keeps moving under us.
    commitMock
      .mockResolvedValueOnce(conflict({ ...FULL, grade: 'Senior' }, 8))
      .mockResolvedValueOnce(conflict({ ...FULL, grade: 'Masters' }, 9));

    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], captureOwnerToken());
    expect(result.status).toBe('conflict');
    expect(commitMock).toHaveBeenCalledTimes(2); // one auto-rebase, no more
    expect(readProfileSyncEnvelope()?.pending?.lockedKeys).toContain('major');

    commitMock.mockClear();
    await flushPendingProfileWrite(captureOwnerToken());
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('an all-keys collision is a conflict, never a success', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    commitMock.mockResolvedValue(conflict({ ...FULL, major: 'Physics', grade: 'Senior' }, 8));
    const result = await stageProfilePatch(
      { ...FULL, major: 'ECE', grade: 'Masters' }, ['major', 'grade'], captureOwnerToken(),
    );
    expect(result.status).toBe('conflict');
    // The working copy is still there — nothing was silently dropped.
    expect(readProfileSyncEnvelope()?.pending).not.toBeNull();
  });

  it('choose-cloud drops the key from the ledger so the next autosave cannot re-stage it', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    // A DURABLE intent: only journal operations count as unconfirmed work now.
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    commitMock.mockResolvedValue(conflict({ ...FULL, major: 'Physics' }, 8));
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(dirtyKeys(token)).toContain('major');

    commitMock.mockClear();
    const resolved = await answerConflict(['major'], 'cloud', token);
    expect(resolved.status).toBe('already-saved');
    expect(dirtyKeys(token)).not.toContain('major');
    expect(rawMirror()?.major).toBe('Physics');
    expect(readProfileSyncEnvelope()?.pending).toBeNull();
  });

  it('choose-local re-sends against the CURRENT revision', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    commitMock.mockResolvedValue(conflict({ ...FULL, major: 'Physics' }, 8));
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);

    commitMock.mockReset();
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE' }, 9));
    const resolved = await answerConflict(['major'], 'local', token);
    expect(resolved.status).toBe('saved');
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(8);
  });
});

describe('the résumé bundle', () => {
  it('staging one half stages both', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, resume_text: 'old', coursework: ['ECE 220'] }, 7));
    await hydrateProfile();
    commitMock.mockResolvedValue(saved({ ...FULL, resume_text: '', coursework: [] }, 8));
    await stageProfilePatch(
      { ...FULL, resume_text: '', coursework: [] }, ['resume_text'], captureOwnerToken(),
    );
    expect(Object.keys(commitMock.mock.calls[0][0].patch).sort()).toEqual(['coursework', 'resume_text']);
  });

  it('a collision on either half conflicts BOTH — coursework never outlives its résumé', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, resume_text: 'old', coursework: ['ECE 220'] }, 7));
    await hydrateProfile();
    // The other device uploaded a NEW résumé while this one removed it.
    commitMock.mockResolvedValue(
      conflict({ ...FULL, resume_text: 'brand new resume', coursework: ['ECE 220'] }, 8),
    );
    const result = await stageProfilePatch(
      { ...FULL, resume_text: '', coursework: [] }, ['resume_text', 'coursework'], captureOwnerToken(),
    );
    expect(result.status).toBe('conflict');
    expect((result as { conflictKeys: string[] }).conflictKeys.sort())
      .toEqual(['coursework', 'resume_text']);
  });
});

describe('skills are an operation, not a list', () => {
  it('an import adds to whatever the other device has — a remote DELETE is not undone', async () => {
    const base = { ...FULL, skills: [{ name: 'Python', level: 'experienced' as const }] };
    loadProfileMock.mockResolvedValue(cloud(base, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    markSkillAdditions([{ name: 'React', level: 'experienced' }], token);

    // The other device DELETED Python and this one only added React.
    const remote = { ...FULL, skills: [] as { name: string; level: 'experienced' }[] };
    commitMock
      .mockResolvedValueOnce(conflict(remote as unknown as ProfileData, 8))
      .mockResolvedValueOnce(saved({ ...remote, skills: [{ name: 'React', level: 'experienced' }] } as unknown as ProfileData, 9));

    const desired = { ...base, skills: [...base.skills, { name: 'React', level: 'experienced' as const }] };
    const result = await stageProfilePatch(desired, ['skills'], token);
    expect(result.status).toBe('saved');
    // Python is NOT resurrected: only the addition was merged in.
    expect(commitMock.mock.calls[1][0].patch.skills).toEqual([{ name: 'React', level: 'experienced' }]);
  });

  it('a remote LEVEL change on an untouched skill is not a conflict', async () => {
    const base = { ...FULL, skills: [{ name: 'Python', level: 'beginner' as const }] };
    loadProfileMock.mockResolvedValue(cloud(base, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    markSkillAdditions([{ name: 'React', level: 'experienced' }], token);

    const remote = { ...FULL, skills: [{ name: 'Python', level: 'expert' as const }] };
    commitMock
      .mockResolvedValueOnce(conflict(remote, 8))
      .mockResolvedValueOnce(saved(remote, 9));
    const desired = { ...base, skills: [...base.skills, { name: 'React', level: 'experienced' as const }] };
    const result = await stageProfilePatch(desired, ['skills'], token);
    expect(result.status).toBe('saved');
    expect(commitMock.mock.calls[1][0].patch.skills).toEqual([
      { name: 'Python', level: 'expert' },
      { name: 'React', level: 'experienced' },
    ]);
  });

  it('the same name at a different level IS a conflict', async () => {
    const base = { ...FULL, skills: [] as { name: string; level: 'expert' }[] };
    loadProfileMock.mockResolvedValue(cloud(base as unknown as ProfileData, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    markSkillAdditions([{ name: 'Rust', level: 'beginner' }], token);
    commitMock.mockResolvedValue(
      conflict({ ...FULL, skills: [{ name: 'Rust', level: 'expert' }] }, 8),
    );
    const result = await stageProfilePatch(
      { ...FULL, skills: [{ name: 'Rust', level: 'beginner' }] }, ['skills'], token,
    );
    expect(result.status).toBe('conflict');
  });

  it('a manual edit turns off additive semantics, and a later import cannot turn them back on', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    markSkillAdditions([{ name: 'React', level: 'experienced' }], token);
    markSkillsReplaced(token);                        // the user deleted something
    markSkillAdditions([{ name: 'Vue', level: 'experienced' }], token); // a later import

    commitMock.mockResolvedValue(conflict({ ...FULL, skills: [{ name: 'Go', level: 'expert' }] }, 8));
    const result = await stageProfilePatch(
      { ...FULL, skills: [{ name: 'React', level: 'experienced' }] }, ['skills'], token,
    );
    // Replace semantics: a remote change to the list is a real disagreement,
    // not something to merge the user's deletion away with.
    expect(result.status).toBe('conflict');
    expect(readProfileSyncEnvelope()?.pending?.skillAdditions).toEqual([]);
  });
});

describe('the outbox', () => {
  it('a newer edit LAYERS onto an unsent one and the older attempt stands down', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();

    let releaseFirst: (v: ProfilePatchOutcome) => void = () => {};
    commitMock.mockImplementationOnce(() => new Promise((r) => { releaseFirst = r; }));
    const first = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    await tick(); // A's request is genuinely in flight now
    // B is staged while A is in flight.
    // A real server gives the second write its OWN revision; two different
    // contents at one revision is refused as malformed, by design.
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE', grade: 'Senior' }, 9));
    const second = stageProfilePatch({ ...FULL, major: 'ECE', grade: 'Senior' }, ['grade'], token);
    await tick();

    releaseFirst(saved({ ...FULL, major: 'ECE' }, 8));
    const [a, b] = await Promise.all([first, second]);
    expect(a.status).toBe('saved');
    // B carries BOTH fields — it layered onto A rather than replacing it.
    const bPatch = commitMock.mock.calls[1][0].patch;
    expect(Object.keys(bPatch).sort()).toEqual(['grade', 'major']);
    expect(b.status).toBe('saved');
  });

  it('an edit made while a save is in flight stays dirty', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();

    let release: (v: ProfilePatchOutcome) => void = () => {};
    commitMock.mockImplementationOnce(() => new Promise((r) => { release = r; }));
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    await tick();
    // The user keeps typing in the SAME field.
    recordProfileIntent({ ...FULL, major: 'ECE again' }, ['major'], token);
    release(saved({ ...FULL, major: 'ECE' }, 8));
    await inFlight;

    // The confirmation describes 'ECE'; the newer edit has nothing else to
    // re-send it, so the key must remain dirty.
    expect(dirtyKeys(token)).toContain('major');
  });

  it('survives a reload and is flushed by the next mount', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], captureOwnerToken());
    expect(readProfileSyncEnvelope()?.pending?.dirtyKeys).toEqual(['major']);

    // A reload wipes the in-memory ledger but not localStorage.
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    commitMock.mockReset();
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE' }, 8));
    const result = await flushPendingProfileWrite(captureOwnerToken());
    expect(result.status).toBe('saved');
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'ECE' });
  });

  it('a partially-sendable write keeps its locked remainder after the sendable half lands', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    // First: lock `major`.
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, major: 'Physics' }, 8));
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(readProfileSyncEnvelope()?.pending?.lockedKeys).toEqual(['major']);

    // Now an unrelated edit: it is sendable, the locked one is not.
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'Physics', grade: 'Senior' }, 9));
    const result = await stageProfilePatch({ ...FULL, grade: 'Senior' }, ['grade'], token);
    // The sendable half landed — and the caller is told the truth about the
    // half that did not. Reporting a clean 'saved' while `major` is still
    // locked is how a UI retires a question that is still open in storage.
    expect(result.status).toBe('conflict');
    expect(result.status === 'conflict' && result.conflictKeys).toEqual(['major']);
    expect(commitMock.mock.calls[1][0].patch).toEqual({ grade: 'Senior' });
    // The user's ECE is still waiting on them — not dropped by the success.
    const pending = readProfileSyncEnvelope()?.pending;
    expect(pending?.lockedKeys).toEqual(['major']);
    expect(pending?.desiredProfile.major).toBe('ECE');
  });

  it('a deleted row keeps the working copy and stops being sendable', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();

    commitMock.mockResolvedValueOnce({ status: 'missing', reason: 'absent' });
    const gone = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(gone.status).toBe('missing');
    // NOT recreated, NOT discarded — kept, and fenced.
    expect(readProfileSyncEnvelope()?.pending?.desiredProfile.major).toBe('ECE');
    expect(readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
    commitMock.mockReset();
    const fenced = await flushPendingProfileWrite(token);
    expect(fenced.status).toBe('missing');
    expect(commitMock, 'a deleted row is never recreated by a replay').not.toHaveBeenCalled();
  });

  it('a merged-away account stops being served at all', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();

    commitMock.mockResolvedValueOnce({ status: 'missing', reason: 'merged_away' });
    const merged = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(merged.status).toBe('missing');
    // The account is dead; its local copy must stop being served.
    expect(rawMirror()).toBeNull();
    expect(readProfileSyncEnvelope()?.pending).toBeNull();
    expect(readProfileSyncEnvelope()?.tombstone?.reason).toBe('merged');
  });
});

describe('local write failures', () => {
  it('a failed envelope write reports device-failed and leaves NO orphan mirror', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const before = rawMirror();
    const realSetItem = window.localStorage.setItem.bind(window.localStorage);
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((key: string, value: string) => {
      if (key === STORAGE_KEYS.PROFILE_SYNC) return; // silent no-op
      realSetItem(key, value);
    });
    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], captureOwnerToken());
    spy.mockRestore();
    expect(result.status).toBe('device-failed');
    expect(commitMock).not.toHaveBeenCalled();
    // A mirror showing an edit with no outbox behind it is an edit that will
    // never be sent and never be reported as unsent.
    expect(rawMirror()).toEqual(before);
  });

  it('a stage that never reached storage is RE-STAGED by the retry, exactly once', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const realSetItem = window.localStorage.setItem.bind(window.localStorage);
    let block = true;
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((key: string, value: string) => {
      if (block && key === STORAGE_KEYS.PROFILE_SYNC) return; // quota / silent no-op
      realSetItem(key, value);
    });
    const failed = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], captureOwnerToken());
    expect(failed).toEqual({ status: 'device-failed', phase: 'stage' });
    expect(commitMock).not.toHaveBeenCalled();
    // There is no outbox entry to flush — a Retry that only looked there
    // would be a permanent no-op.
    expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();

    block = false;
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE' }, 8));
    const retried = await flushPendingProfileWrite(captureOwnerToken());
    spy.mockRestore();
    expect(retried.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'ECE' });
    expect(rawMirror()?.major).toBe('ECE');

    // ... and exactly once: a second retry has nothing left to do.
    commitMock.mockClear();
    const again = await flushPendingProfileWrite(captureOwnerToken());
    expect(again.status).toBe('blocked');
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('a cloud success this browser could not record retries the LOCAL write only', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    // The confirmed row differs from the optimistic one (another device's
    // grade came back with it), so a blocked write is actually detectable:
    // a no-op whose old value happens to equal the new one reads back as a
    // success, and rightly so.
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE', grade: 'Senior' }, 8));

    // The optimistic stage write is allowed; the one that records the CLOUD's
    // confirmation is not — that is the state this test is about.
    let profileWrites = 0;
    let block = true;
    const realSetItem = window.localStorage.setItem.bind(window.localStorage);
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((key: string, value: string) => {
      if (key === STORAGE_KEYS.PROFILE) {
        profileWrites += 1;
        if (block && profileWrites > 1) return;
      }
      realSetItem(key, value);
    });
    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], captureOwnerToken());
    expect(result.status).toBe('device-failed');
    expect((result as { phase: string }).phase).toBe('confirm');

    block = false;
    commitMock.mockClear();
    const repaired = await flushPendingProfileWrite(captureOwnerToken());
    spy.mockRestore();
    // The request already succeeded — re-sending it would be a save against a
    // revision that has moved on.
    expect(commitMock).not.toHaveBeenCalled();
    expect(repaired.status).toBe('already-saved');
    expect(rawMirror()?.major).toBe('ECE');
    expect(rawMirror()?.grade).toBe('Senior');
  });
});

describe('identity', () => {
  it('a stale token writes nothing', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const stale = captureOwnerToken();
    await seedOwner('sync-u2');
    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], stale);
    expect(result.status).toBe('abandoned');
    expect(commitMock).not.toHaveBeenCalled();
  });
});

describe('key ownership across writers', () => {
  it("the home form never re-sends another writer's unsent key with its own snapshot", async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();

    // The school gate stages home_school=mit and the request fails: it stays
    // in the outbox. The home form still shows 'uiuc' — it mounted before the
    // broadcast, or the broadcast never reached it.
    commitMock.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    await stageProfilePatch({ ...FULL, home_school: 'mit' }, ['home_school'], token);
    expect(readProfileSyncEnvelope()?.pending?.desiredProfile.home_school).toBe('mit');

    // An unrelated home-form edit. It owns 'grade' and NOTHING else.
    recordProfileIntent({ ...FULL, grade: 'Senior' }, ['grade'], token, { writer: HOME_FORM_WRITER });
    expect(dirtyKeys(token, HOME_FORM_WRITER)).toEqual(['grade']);
    commitMock.mockResolvedValueOnce(saved({ ...FULL, home_school: 'mit', grade: 'Senior' }, 8));
    await stageProfilePatch(
      { ...FULL, grade: 'Senior' },            // stale: still says uiuc
      dirtyKeys(token, HOME_FORM_WRITER),
      token,
      { allowCreate: true },
    );

    // The campus the user picked is still mit — the home form's stale snapshot
    // did not carry it back to uiuc.
    const patch = commitMock.mock.calls[1][0].patch;
    expect(patch.home_school).toBe('mit');
    expect(patch.grade).toBe('Senior');
  });
});

describe('skills operation lifecycle', () => {
  it('survives a reload, and an unrelated edit does not turn additive off', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    markSkillAdditions([{ name: 'React', level: 'experienced' }], token);
    commitMock.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    await stageProfilePatch(
      { ...FULL, skills: [...FULL.skills, { name: 'React', level: 'experienced' }] },
      ['skills'], token,
    );

    // Reload: the in-memory operation ledger is gone, the outbox is not.
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();

    // An unrelated edit re-stages; skills must STILL be additive.
    const remote = { ...FULL, skills: [] as { name: string; level: 'experienced' }[] };
    commitMock.mockReset();
    commitMock
      .mockResolvedValueOnce(conflict(remote as unknown as ProfileData, 8))
      .mockResolvedValueOnce(saved({ ...remote, grade: 'Senior', skills: [{ name: 'React', level: 'experienced' }] } as unknown as ProfileData, 9));
    await stageProfilePatch(
      { ...FULL, grade: 'Senior', skills: [...FULL.skills, { name: 'React', level: 'experienced' }] },
      ['grade'], captureOwnerToken(),
    );
    // Python (deleted remotely) is NOT resurrected by the rebase.
    expect(commitMock.mock.calls[1][0].patch.skills).toEqual([{ name: 'React', level: 'experienced' }]);
  });

  it('a confirmed save consumes the additions, so the next import sends only the new one', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();

    markSkillAdditions([{ name: 'React', level: 'experienced' }], token);
    const afterReact = { ...FULL, skills: [...FULL.skills, { name: 'React', level: 'experienced' as const }] };
    commitMock.mockResolvedValueOnce(saved(afterReact, 8));
    await stageProfilePatch(afterReact, ['skills'], token);

    // The other device then DELETES React and this one imports Vue.
    markSkillAdditions([{ name: 'Vue', level: 'experienced' }], token);
    const remote = { ...FULL, skills: [{ name: 'Python', level: 'experienced' as const }] };
    commitMock
      .mockResolvedValueOnce(conflict(remote, 9))
      .mockResolvedValueOnce(saved({ ...remote, skills: [...remote.skills, { name: 'Vue', level: 'experienced' as const }] }, 10));
    await stageProfilePatch(
      { ...afterReact, skills: [...afterReact.skills, { name: 'Vue', level: 'experienced' as const }] },
      ['skills'], token,
    );
    // React was already confirmed once; re-adding it here would undo the other
    // device's deletion.
    expect(commitMock.mock.calls[2][0].patch.skills).toEqual([
      { name: 'Python', level: 'experienced' },
      { name: 'Vue', level: 'experienced' },
    ]);
  });

  it('a manual replace stops being sticky once its own write is confirmed', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    markSkillsReplaced(token);
    const replaced = { ...FULL, skills: [{ name: 'Go', level: 'expert' as const }] };
    commitMock.mockResolvedValueOnce(saved(replaced, 8));
    await stageProfilePatch(replaced, ['skills'], token);
    expect(readProfileSyncEnvelope()?.pending).toBeNull();

    // A LATER pure import is additive again — the deletion it must not undo
    // has already been stored.
    markSkillAdditions([{ name: 'Rust', level: 'beginner' }], token);
    const remote = { ...replaced, skills: [{ name: 'Go', level: 'expert' as const }, { name: 'Zig', level: 'beginner' as const }] };
    commitMock
      .mockResolvedValueOnce(conflict(remote, 9))
      .mockResolvedValueOnce(saved(remote, 10));
    const result = await stageProfilePatch(
      { ...replaced, skills: [...replaced.skills, { name: 'Rust', level: 'beginner' as const }] },
      ['skills'], token,
    );
    expect(result.status).toBe('saved');
    expect(commitMock.mock.calls[2][0].patch.skills).toEqual([
      { name: 'Go', level: 'expert' },
      { name: 'Zig', level: 'beginner' },
      { name: 'Rust', level: 'beginner' },
    ]);
  });
});

describe('skills: two imports racing one response', () => {
  it('confirming the first import does NOT let it ride along on the second', async () => {
    const base = { ...FULL, skills: [{ name: 'Python', level: 'experienced' as const }] };
    loadProfileMock.mockResolvedValue(cloud(base, 7));
    await hydrateProfile();
    const token = captureOwnerToken();

    // A: import React. Its request is in flight.
    markSkillAdditions([{ name: 'React', level: 'experienced' }], token);
    let releaseA: (v: ProfilePatchOutcome) => void = () => {};
    commitMock.mockImplementationOnce(() => new Promise((r) => { releaseA = r; }));
    const withReact = { ...base, skills: [...base.skills, { name: 'React', level: 'experienced' as const }] };
    const a = stageProfilePatch(withReact, ['skills'], token);
    await tick();

    // B: a second import lands while A is still out.
    markSkillAdditions([{ name: 'Vue', level: 'experienced' }], token);
    releaseA(saved(withReact, 8));
    await a;

    // The other device then DELETES React. B is staged now and conflicts.
    const remote = { ...FULL, skills: [{ name: 'Python', level: 'experienced' as const }] };
    commitMock.mockReset();
    commitMock
      .mockResolvedValueOnce(conflict(remote, 9))
      .mockResolvedValueOnce(saved({ ...remote, skills: [...remote.skills, { name: 'Vue', level: 'experienced' as const }] }, 10));
    const withVue = { ...withReact, skills: [...withReact.skills, { name: 'Vue', level: 'experienced' as const }] };
    const result = await stageProfilePatch(withVue, ['skills'], token);

    expect(result.status).toBe('saved');
    // React was A's, already confirmed and since deleted elsewhere. Only B's
    // Vue may ride on this write.
    expect(commitMock.mock.calls[1][0].patch.skills).toEqual([
      { name: 'Python', level: 'experienced' },
      { name: 'Vue', level: 'experienced' },
    ]);
  });
});

describe('the journal is the authority, not this process\'s memory', () => {
  it('a malformed journal stops the save — a live cache does NOT stand in for it', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    commitMock.mockClear();

    // Another tab's operation, unreadable by this build.
    localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_corrupt`, '{not json');

    const keys = getDirtyProfileKeys(token, HOME_FORM_WRITER);
    expect(keys.ok).toBe(false);

    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(result.status).toBe('device-failed');
    // ZERO requests: sending while another tab's edit is invisible is the
    // lost update the journal exists to prevent.
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('a reload plus a new edit keeps the EARLIEST frozen base', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    // Edit one: CS -> ECE, based on revision 7.
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);

    // A reload: the in-memory cache is gone, the journal is not. Another
    // device has since moved the row to revision 9.
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, grade: 'Senior' }, 9));
    await hydrateProfile();
    // Edit two on the same field, after the reload.
    recordProfileIntent({ ...FULL, major: 'ECE then Physics' }, ['major'], token);

    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE then Physics' }, 10));
    await stageProfilePatch({ ...FULL, major: 'ECE then Physics' }, ['major'], token);

    // The write is made against revision 7 — where the edit chain STARTED —
    // not against the 9 the reload happened to see. Anything else silently
    // agrees to overwrite whatever moved the row in between.
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(7);
  });

  it('a confirmed save CONSUMES its journal operations', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    const before = getDirtyProfileKeys(token);
    expect(before.ok && before.value).toEqual(['major']);

    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE' }, 8));
    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(result.status).toBe('saved');

    // Left in the journal it would be re-sent on the next mount as if it had
    // never landed — a duplicate save, and a duplicate history row.
    const after = getDirtyProfileKeys(token);
    expect(after.ok && after.value).toEqual([]);
    resetProfileDirtyLedger();
    const persisted = getDirtyProfileKeys(captureOwnerToken());
    expect(persisted.ok && persisted.value).toEqual([]);
  });

  it('two origins wanting different things for one field is a LOCAL conflict — zero requests', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    // This tab's edit, made against revision 7.
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);

    // Another tab, which had already seen revision 9, edits the SAME field to
    // something else. Sending this tab's value and leaving that operation
    // unacknowledged would silently discard it.
    localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_0000othertab`, JSON.stringify({
      opId: '0000othertab', originId: 'other-tab', lineage: 'other-tab',
      fields: [{ key: 'major', base: { present: true, value: 'CS' },
        desired: { present: true, value: 'Physics II' } }],
      baseRevision: 9, writer: 'home-form', mode: 'set', seq: 1,
    }));

    resetProfileDirtyLedger();
    commitMock.mockClear();
    const result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);

    expect(commitMock).not.toHaveBeenCalled();
    expect(result.status).toBe('conflict');
    expect((result as { conflictKeys: string[] }).conflictKeys).toContain('major');
    // Both operations are still there — neither user's edit was thrown away.
    const keys = getDirtyProfileKeys(token, HOME_FORM_WRITER);
    expect(keys.ok && keys.value).toContain('major');
  });

  it('the same origin editing twice sends ONLY the latest, against the EARLIEST base', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    // A reload moves the row on; the same tab keeps typing.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, grade: 'Senior' }, 9));
    await hydrateProfile();
    recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token);

    commitMock.mockResolvedValue(saved({ ...FULL, major: 'Physics' }, 10));
    const result = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token);

    expect(result.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    // Latest intention, oldest base — one write, not two.
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'Physics' });
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(7);
    // ... and the WHOLE chain is acknowledged, not just the last operation.
    const after = getDirtyProfileKeys(token);
    expect(after.ok && after.value).toEqual([]);
  });

  it('a chain is resolved against its EARLIEST base, not its latest', async () => {
    // A same-origin chain whose operations record different bases — a draft
    // assembled across builds, or by a future writer. Which one the plan
    // takes is observable: with the earliest, the remote value still equals
    // the base and the edit applies; with the latest, it looks like a
    // three-way conflict the user never caused.
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    await hydrateProfile();
    const P = STORAGE_KEYS.PROFILE_JOURNAL_PREFIX;
    localStorage.setItem(`${P}op_chain1`, JSON.stringify({
      opId: 'chain1', originId: 'one-tab', lineage: 'one-tab', seq: 1, baseRevision: 7,
      writer: 'default', mode: 'set',
      fields: [{ key: 'major', base: { present: true, value: 'CS' },
        desired: { present: true, value: 'ECE' } }],
    }));
    localStorage.setItem(`${P}op_chain2`, JSON.stringify({
      opId: 'chain2', originId: 'one-tab', lineage: 'one-tab', seq: 2, baseRevision: 7,
      writer: 'default', mode: 'set',
      fields: [{ key: 'major', base: { present: true, value: 'ECE' },
        desired: { present: true, value: 'Physics' } }],
    }));
    resetProfileDirtyLedger();

    // The server rejects at revision 7 and reports the row still says CS.
    commitMock
      .mockResolvedValueOnce(conflict(FULL, 8))
      .mockResolvedValueOnce(saved({ ...FULL, major: 'Physics' }, 9));
    const result = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], captureOwnerToken());

    // remote === the chain's EARLIEST base ('CS'), so nobody else touched the
    // field and the edit rebases cleanly.
    expect(result.status).toBe('saved');
    expect(commitMock.mock.calls[1][0].patch).toEqual({ major: 'Physics' });
  });

  it('a journal write that fails leaves NO half-recorded action', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, resume_text: 'r', coursework: ['ECE 220'] }, 7));
    await hydrateProfile();
    const token = captureOwnerToken();
    const realSet = window.localStorage.setItem.bind(window.localStorage);
    const spy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((k: string, v: string) => {
      if (k.startsWith(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_`)) return; // storage refuses
      realSet(k, v);
    });
    // The résumé bundle is TWO fields in ONE operation, so a refused write
    // records neither — never resume_text cleared with its coursework intact.
    const recorded = recordProfileIntent(
      { ...FULL, resume_text: '', coursework: [] }, ['resume_text'], token,
    );
    spy.mockRestore();
    expect(recorded).toBe(false);
    const keys = getDirtyProfileKeys(token);
    expect(keys.ok && keys.value).toEqual([]);
  });
});

/** The journal as it is actually stored — not a view this module keeps. */
function journalOps(): JournalOp[] {
  const read = readOutstandingOps();
  if (!read.ok) throw new Error(`journal unreadable: ${read.reason}`);
  return read.value;
}

describe('a real reload is a new document, and its edits continue the same draft', () => {
  /** What a browser reload actually does to this module: the DOCUMENT is new
   *  (a fresh origin id, an empty in-memory cache) while localStorage — the
   *  journal, the envelope, the mirror — survives untouched. Nothing here
   *  clears storage; that would delete the very state under test. */
  /** A new document over the SAME storage — localStorage and sessionStorage
   *  both untouched, module globals fresh. The only thing that distinguishes
   *  a reload from a window opened next to it is `kind`. */
  function openDocument(kind: 'reload' | 'other') {
    startDocumentForTests(kind);
  }
  function reloadDocument() {
    openDocument('reload');
    resetProfileDirtyLedger();
  }

  it('an edit made after the reload supersedes the exact operations it was made from, and sends', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();

    // Pre-reload: the user edits, and the tab closes inside the debounce.
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const before = journalOps();
    expect(before).toHaveLength(1);

    reloadDocument();

    // The reloaded document reads the draft back and SHOWS it — that is what
    // makes the next edit a continuation rather than an independent opinion.
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const hydrated = await hydrateProfile();
    expect(hydrated.profile?.major).toBe('ECE');
    expect(hydrated.conflictKeys).toEqual([]);

    // The user changes their mind. A DIFFERENT origin id now, so nothing but
    // an explicit ancestry can tell this apart from another tab.
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const after = journalOps();
    const continuation = after.find((op) => op.originId !== before[0].originId);
    expect(continuation).toBeDefined();
    expect(continuation!.supersedes).toEqual([before[0].opId]);

    commitMock.mockResolvedValue(saved({ ...FULL, major: 'Physics' }, 5));
    const result = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token);
    expect(result.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'Physics' });
    // Both operations are settled by that one save: the pre-reload draft is
    // not left behind to be re-sent as if it were somebody else's edit.
    expect(journalOps()).toHaveLength(0);
  });

  it('a window opened from this one — cloned sessionStorage and all — is NOT a continuation', async () => {
    // The hole a tab id alone cannot close. `window.open` hands the new
    // window a COPY of this one's sessionStorage, and "Duplicate tab" does
    // the same; localStorage is shared outright and the module globals are
    // fresh. Every stored mark of identity is therefore identical to a
    // reload's. What differs is how the document came to exist, and that is
    // the only thing allowed to grant continuity.
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const [first] = journalOps();

    // The new window: same storage, fresh document, NOT a reload.
    openDocument('other');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const hydrated = await hydrateProfile();
    expect(hydrated.profile?.major).toBe('ECE'); // it can SEE the other draft

    // …and seeing it is not the same as owning it.
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const rival = journalOps().find((op) => op.opId !== first.opId)!;
    expect(rival.supersedes ?? []).toEqual([]);

    commitMock.mockClear();
    const result = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token);
    expect(result.status).toBe('conflict');
    expect(commitMock).not.toHaveBeenCalled();
    expect(journalOps()).toHaveLength(2);
  });

  it('reloading the duplicated window still cannot claim the original\'s operations', async () => {
    // The follow-up hole: the clone inherited a lineage id, so if it merely
    // declined to USE it once, its own first reload would pick it up and
    // claim the original's edits after all. The inherited value has to be
    // gone, not just ignored.
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const [first] = journalOps();

    openDocument('other');       // duplicated window, cloned session state
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    await hydrateProfile();
    openDocument('reload');      // …and now IT reloads
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    await hydrateProfile();

    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const rival = journalOps().find((op) => op.opId !== first.opId)!;
    expect(rival.supersedes ?? []).toEqual([]);

    commitMock.mockClear();
    const result = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token);
    expect(result.status).toBe('conflict');
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('a reload that cannot prove its lineage conflicts rather than assuming one', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const [first] = journalOps();

    // Session storage stops working — private mode, a full quota, a browser
    // that refuses it outright. The document says it is a reload and cannot
    // show what it is a reload OF. (Replacing the accessor, not spying on the
    // methods: jsdom's Storage is a proxy that turns a method assignment into
    // a stored key, so a spy there would silently do nothing.)
    const realSession = window.sessionStorage;
    const refuse = () => { throw new Error('SecurityError'); };
    Object.defineProperty(window, 'sessionStorage', {
      configurable: true,
      get: () => ({ getItem: refuse, setItem: refuse, removeItem: refuse }),
    });
    try {
      openDocument('reload');
      resetProfileDirtyLedger();
      loadProfileMock.mockResolvedValue(cloud(FULL, 4));
      await hydrateProfile();
      expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);

      const rival = journalOps().find((op) => op.opId !== first.opId)!;
      expect(rival.supersedes ?? []).toEqual([]);
      commitMock.mockClear();
      const result = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token);
      expect(result.status).toBe('conflict');
      expect(commitMock).not.toHaveBeenCalled();
    } finally {
      // Restored even when an assertion above throws: leaving a refusing
      // sessionStorage behind would fail every test after this one for a
      // reason that has nothing to do with them.
      Object.defineProperty(window, 'sessionStorage', { configurable: true, value: realSession });
    }
  });

  it('classifies a real navigation entry, not just the test seam', async () => {
    // Everything above drives the navigation kind directly. This one lets the
    // module read it the way it does in a browser, so the classification
    // itself is under test: a `navigate` entry is not a reload, and anything
    // it does not recognise is not a reload either.
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const [first] = journalOps();

    const entries = vi.spyOn(performance, 'getEntriesByType').mockReturnValue(
      [{ type: 'navigate' } as unknown as PerformanceEntry],
    );
    startDocumentForTests(null);   // no override: ask the browser
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    expect(journalOps().find((op) => op.opId !== first.opId)!.supersedes ?? []).toEqual([]);

    commitMock.mockClear();
    expect((await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token)).status)
      .toBe('conflict');
    expect(commitMock).not.toHaveBeenCalled();
    entries.mockRestore();
  });

  it('a reload reported BY THE BROWSER is a continuation', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const [first] = journalOps();

    const entries = vi.spyOn(performance, 'getEntriesByType').mockReturnValue(
      [{ type: 'reload' } as unknown as PerformanceEntry],
    );
    startDocumentForTests(null);
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    expect(journalOps().find((op) => op.opId !== first.opId)!.supersedes ?? [])
      .toEqual([first.opId]);
    entries.mockRestore();
  });

  it('a navigation entry the browser does not classify is NOT a reload', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const [first] = journalOps();

    const entries = vi.spyOn(performance, 'getEntriesByType').mockReturnValue([]);
    startDocumentForTests(null);
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    expect(journalOps().find((op) => op.opId !== first.opId)!.supersedes ?? []).toEqual([]);
    entries.mockRestore();
  });

  it('a DIFFERENT tab editing the same field is still a conflict, with zero requests', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    // A second TAB: a new origin that never adopted the first tab's operation
    // — it has its own form, hydrated before that edit existed. No reload, no
    // hydrate, so nothing was observed to continue from.
    resetJournalLaneForTests();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const ops = journalOps();
    expect(ops).toHaveLength(2);
    for (const op of ops) expect(op.supersedes ?? []).toEqual([]);

    commitMock.mockClear();
    const result = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token);
    expect(result.status).toBe('conflict');
    expect(commitMock).not.toHaveBeenCalled();
    // Neither value is thrown away while the disagreement stands.
    expect(journalOps()).toHaveLength(2);
  });

  it('adoption is per KEY: continuing one field does not claim another tab\'s edit to a different one', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    reloadDocument();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    await hydrateProfile();

    // Another tab writes a DIFFERENT field after this document hydrated.
    const otherTab = { ...FULL, college: 'LAS' };
    resetJournalLaneForTests();
    expect(recordProfileIntent(otherTab, ['college'], token)).toBe(true);
    const collegeOp = journalOps().find((op) => op.fields.some((f) => f.key === 'college'))!;

    // Back in the reloaded document, continuing `major`.
    reloadDocument();
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const majorOp = journalOps()
      .filter((op) => op.fields.some((f) => f.key === 'major'))
      .find((op) => op.fields[0].desired.present && op.fields[0].desired.value === 'Physics')!;
    expect(majorOp.supersedes ?? []).not.toContain(collegeOp.opId);
  });
});

describe('a composite operation across two passes settles exactly once, at the end', () => {
  /** One action, two fields, and a collision on the second. Pass 1 sends the
   *  safe field; the operation must survive it. Pass 2 is the user's explicit
   *  answer, and only then is the whole thing done with. */
  async function partialSend(token: ReturnType<typeof captureOwnerToken>) {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, college: 'Grainger', major: 'CS' }, 1));
    await hydrateProfile();
    expect(recordProfileIntent(
      { ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token,
    )).toBe(true);
    const [composite] = journalOps();

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, college: 'Grainger', major: 'ECE' }, 2));
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'LAS', major: 'ECE' }, 3));
    const first = await stageProfilePatch(
      { ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token,
    );
    expect(first.status).toBe('conflict');
    expect((first as { conflictKeys: string[] }).conflictKeys).toEqual(['major']);
    // The safe half landed and the operation is STILL outstanding: what it
    // asked for in `major` is not what the row holds.
    expect(commitMock.mock.calls.at(-1)?.[0].patch).toEqual({ college: 'LAS' });
    expect(journalOps().map((op) => op.opId)).toEqual([composite.opId]);
    return composite;
  }

  it('Keep Local: the second send makes every field canonical, and settles it once', async () => {
    const token = captureOwnerToken();
    const composite = await partialSend(token);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'LAS', major: '' }, 4));
    const resolved = await answerConflict(['major'], 'local', token);

    expect(resolved.status).toBe('saved');
    // Only the field that was actually in dispute goes out again — the safe
    // half is already canonical and re-sending it would be a blind write.
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: '' });
    // Settled exactly once, and only now: every field it carried is what the
    // row holds. The replacement operation goes with it — nothing is left
    // behind to be re-sent as if it had never been answered.
    expect(journalOps()).toEqual([]);
    expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();
    expect(getDirtyProfileKeys(token, HOME_FORM_WRITER)).toEqual({ ok: true, value: [] });
    expect(composite.fields).toHaveLength(2); // it really was one action
  });

  it('Use Cloud: the locked field is dropped, the safe half is NOT re-sent, and it closes', async () => {
    const token = captureOwnerToken();
    await partialSend(token);

    commitMock.mockReset();
    const resolved = await answerConflict(['major'], 'cloud', token);

    expect(resolved.status).toBe('already-saved');
    expect(commitMock).not.toHaveBeenCalled(); // nothing left to say
    expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();
    // The other device's value is what this browser now holds…
    expect(rawMirror()?.major).toBe('ECE');
    // …and the safe half of the same action is still the value that landed.
    expect(rawMirror()?.college).toBe('LAS');
    // Whatever is left on disk, nothing ASKS for anything any more: a fresh
    // reader finds no unsent work and no conflict.
    startDocumentForTests('other');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, college: 'LAS', major: 'ECE' }, 3));
    const reread = await hydrateProfile();
    expect(reread.conflictKeys).toEqual([]);
    expect(reread.hasPending).toBe(false);
    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock).not.toHaveBeenCalled();
  });
});

describe('an answer to a conflict is made against the revision that is current NOW', () => {
  it('Keep Local re-sends against today\'s revision, not the one the replaced edit started from', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    // Another device got there first.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, major: 'Physics' }, 2));
    const first = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(first.status).toBe('conflict');
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(1);

    // "Keep what I typed" is a NEW intent: the user has now seen revision 2
    // and chosen their value over it. Sending it against revision 1 — the one
    // the replaced operation started from — would collide with the very
    // change they just looked at, forever.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 3));
    const resolved = await answerConflict(['major'], 'local', token);

    expect(resolved.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0]).toMatchObject({
      expectedRevision: 2,
      patch: { major: 'ECE' },
    });
    expect(journalOps()).toEqual([]);
  });
});

describe('a settled field can also be one a later edit took over', () => {
  it('a composite whose safe field was re-edited afterwards still settles, and the newer value never regresses', async () => {
    // Three stages, and the trap is in the third:
    //   A: one action setting college AND major. major collides and locks.
    //   B: a later edit changes college again — A's own value for it is now
    //      history, and the row will never hold it again.
    //   C: the user answers A's collision with Keep Local.
    // If A may only settle when the row holds what A asked for, A can never
    // settle at all. It becomes a zombie the next outbox rebuild can read and
    // re-send, putting the OLD college back over the newer one.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, college: 'Grainger', major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    expect(recordProfileIntent(
      { ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token,
    )).toBe(true);
    const [composite] = journalOps();

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, college: 'Grainger', major: 'ECE' }, 2));
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'LAS', major: 'ECE' }, 3));
    expect((await stageProfilePatch(
      { ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token,
    )).status).toBe('conflict');
    expect(journalOps().map((o) => o.opId)).toEqual([composite.opId]);

    // B: college moves on.
    expect(recordProfileIntent({ ...FULL, college: 'Media', major: '' }, ['college'], token)).toBe(true);
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'Media', major: 'ECE' }, 4));
    expect((await stageProfilePatch({ ...FULL, college: 'Media', major: '' }, ['college'], token)).status)
      .toBe('conflict');

    // C: the collision is answered.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'Media', major: '' }, 5));
    expect((await answerConflict(['major'], 'local', token)).status).toBe('saved');

    // Nothing is left behind…
    expect(journalOps()).toEqual([]);
    expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();
    // …so the next flush has nothing to say…
    commitMock.mockReset();
    expect((await flushPendingProfileWrite(token)).status).toBe('blocked');
    expect(commitMock).not.toHaveBeenCalled();
    // …and the newest college is what everything reads, on this device and in
    // the row. The value A wanted is gone for good.
    expect(rawMirror()?.college).toBe('Media');
    expect(readProfileSyncEnvelope()?.confirmed?.profile.college).toBe('Media');
  });

  it('an unanswered collision still keeps its operation, even when the safe field moved on', async () => {
    // The same shape, stopping before the answer: `major` is still locked, so
    // the operation that carries it stays. Settling it here would be the data
    // loss the rule above must not open the door to.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, college: 'Grainger', major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(
      { ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token,
    )).toBe(true);
    const [composite] = journalOps();

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, college: 'Grainger', major: 'ECE' }, 2));
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'LAS', major: 'ECE' }, 3));
    await stageProfilePatch({ ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token);

    expect(recordProfileIntent({ ...FULL, college: 'Media', major: '' }, ['college'], token)).toBe(true);
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'Media', major: 'ECE' }, 4));
    await stageProfilePatch({ ...FULL, college: 'Media', major: '' }, ['college'], token);

    const survivor = journalOps().find((o) => o.opId === composite.opId);
    expect(survivor, 'the operation carrying the locked field must survive').toBeDefined();
    expect(survivor!.fields.find((f) => f.key === 'major')?.desired)
      .toEqual({ present: true, value: '' });
  });
});

describe('answering ONE locked field leaves the evidence for the others', () => {
  it('Use Cloud on one of two locked fields keeps the other one\'s value, durably', async () => {
    // One action touching three fields. Two of them collide. The user answers
    // ONE of the two — and the operation carrying all three is the only
    // record of what they wanted for the third. Settling it wholesale to
    // discard the answered field would take that with it.
    loadProfileMock.mockResolvedValue(cloud(
      { ...FULL, college: 'Grainger', major: 'CS', grade: 'Junior' }, 1,
    ));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(
      { ...FULL, college: 'LAS', major: 'Physics', grade: 'Senior' },
      ['college', 'major', 'grade'],
      token,
    )).toBe(true);

    // Another device moved major AND grade; college is untouched and safe.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict(
      { ...FULL, college: 'Grainger', major: 'ECE', grade: 'Masters' }, 2,
    ));
    commitMock.mockResolvedValueOnce(saved(
      { ...FULL, college: 'LAS', major: 'ECE', grade: 'Masters' }, 3,
    ));
    const first = await stageProfilePatch(
      { ...FULL, college: 'LAS', major: 'Physics', grade: 'Senior' },
      ['college', 'major', 'grade'],
      token,
    );
    expect(first.status).toBe('conflict');
    expect((first as { conflictKeys: string[] }).conflictKeys.sort()).toEqual(['grade', 'major']);

    // The user takes the other device's `major` — and says nothing about
    // `grade`.
    commitMock.mockReset();
    await answerConflict(['major'], 'cloud', token);

    // `grade` is still theirs to decide: the value they typed is still here,
    // still locked, and still survives a reload.
    const pending = readProfileSyncEnvelope()?.pending;
    expect(pending?.lockedKeys).toEqual(['grade']);
    expect((pending?.desiredProfile as unknown as Record<string, unknown>).grade).toBe('Senior');
    const stillWanted = journalOps().flatMap((op) => op.fields).find((f) => f.key === 'grade');
    expect(stillWanted?.desired, 'the journal must still say what grade the user wanted')
      .toEqual({ present: true, value: 'Senior' });
    // …while the answered field really is the other device's now. The
    // operation that carried both fields is still on disk — it is still owed
    // for `grade` — but nothing ASKS for major any more: a fresh reader sees
    // the receipt, not a live disagreement.
    expect(rawMirror()?.major).toBe('ECE');
    startDocumentForTests('other');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud(
      { ...FULL, college: 'LAS', major: 'ECE', grade: 'Masters' }, 3,
    ));
    const reread = await hydrateProfile();
    expect(reread.profile?.major).toBe('ECE');
    expect(reread.conflictKeys).toEqual(['grade']);
  });
});

describe('a response settles only what its own request captured', () => {
  it('an edit recorded while the request was in flight is never absorbed by its answer', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    let release: (() => void) | undefined;
    commitMock.mockReset();
    commitMock.mockImplementationOnce(() => new Promise<ProfilePatchOutcome>((resolve) => {
      release = () => resolve(saved({ ...FULL, major: 'ECE' }, 2));
    }));
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    expect(release, 'the request must actually be in flight').toBeDefined();

    // The user keeps typing. This operation continues the one in flight — it
    // supersedes it — but the server has never seen it.
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const later = journalOps().find((op) => (op.supersedes ?? []).length > 0)!;
    expect(later, 'the later edit was recorded').toBeDefined();

    release!();
    await inFlight;

    // The answer is about ECE. Physics was never sent, so it is still owed:
    // deleting it here — because it happens to descend from what WAS sent —
    // loses an edit the user made and would leave the field looking saved.
    expect(journalOps().map((op) => op.opId)).toEqual([later.opId]);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'Physics' }, 3));
    const next = await flushPendingProfileWrite(token);
    expect(next.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'Physics' });
    expect(journalOps()).toEqual([]);
    expect(rawMirror()?.major).toBe('Physics');
  });
});

describe('an acknowledgement rebases the edits that continue it', () => {
  it('B, recorded while A was in flight, sends against the revision A produced', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    let release: (() => void) | undefined;
    commitMock.mockReset();
    commitMock.mockImplementationOnce((intent) => new Promise<ProfilePatchOutcome>((resolve) => {
      release = () => resolve(server.handle(intent) as ProfilePatchOutcome);
    }));

    // A: CS -> ECE, in flight.
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    expect(release, 'A must actually be in flight').toBeDefined();

    // B: the user keeps typing. While A is outstanding B correctly inherits
    // the earliest base — CS at revision 1 — because that is still all this
    // device knows the row to be.
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const b = journalOps().find((op) => (op.supersedes ?? []).length > 0)!;
    expect(b.baseRevision).toBe(1);
    expect(b.fields[0].base).toEqual({ present: true, value: 'CS' });

    release!();
    await inFlight;
    expect(server.rev).toBe(2);

    // A landed. B is still owed — and it is the user's own next keystroke on
    // the same field, not a disagreement with anyone. Leaving it based on CS
    // at revision 1 aims the next CAS at a row that no longer exists.
    const survivor = journalOps().find((op) => op.opId === b.opId)!;
    expect(survivor, 'B survives: it was never sent').toBeDefined();
    // B's own bytes are UNTOUCHED — operation keys are append-only, and an
    // operation appended after any scan could never be rewritten anyway.
    expect(survivor.baseRevision).toBe(1);
    expect(survivor.fields[0].base).toEqual({ present: true, value: 'CS' });
    expect(survivor.fields[0].desired, 'its intent is its own')
      .toEqual({ present: true, value: 'Physics' });

    // The base it will actually be SENT against is derived, by following its
    // explicit ancestry through the acknowledgement receipt A left behind.
    const receipts = readRebaseReceipts();
    expect(receipts.ok).toBe(true);
    const effective = effectiveOpBase(survivor, receipts.ok ? receipts.value : new Map());
    expect(effective.baseRevision, 'rebased onto what A confirmed').toBe(2);
    expect(effective.fields[0].base).toEqual({ present: true, value: 'ECE' });

    commitMock.mockReset();
    commitMock.mockImplementation((intent) => Promise.resolve(server.handle(intent) as ProfilePatchOutcome));
    const next = await flushPendingProfileWrite(token);

    expect(next.status, 'no manufactured conflict against the user\'s own edit').toBe('saved');
    expect(server.seen.at(-1)).toEqual({ expected: 2, patch: { major: 'Physics' } });
    expect(server.row.major).toBe('Physics');
    expect(journalOps()).toEqual([]);
  });

  it('the rebase is DURABLE: a reload between the acknowledgement and B\'s send sees it', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    let release: (() => void) | undefined;
    commitMock.mockReset();
    commitMock.mockImplementationOnce((intent) => new Promise<ProfilePatchOutcome>((resolve) => {
      release = () => resolve(server.handle(intent) as ProfilePatchOutcome);
    }));
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    release!();
    await inFlight;

    // The tab is reloaded. Every in-memory cache is gone; only what reached
    // storage survives — which is the point of rebasing the JOURNAL and not
    // just the map.
    resetProfileDirtyLedger();
    const reread = journalOps().find((op) => (op.supersedes ?? []).length > 0)!;
    const receipts = readRebaseReceipts();
    expect(receipts.ok, 'the receipt is on disk, not in a cache').toBe(true);
    const effective = effectiveOpBase(reread, receipts.ok ? receipts.value : new Map());
    expect(effective.baseRevision).toBe(2);
    expect(effective.fields[0].base).toEqual({ present: true, value: 'ECE' });

    commitMock.mockReset();
    commitMock.mockImplementation((intent) => Promise.resolve(server.handle(intent) as ProfilePatchOutcome));
    const next = await flushPendingProfileWrite(token);
    expect(next.status).toBe('saved');
    expect(server.seen.at(-1)).toEqual({ expected: 2, patch: { major: 'Physics' } });
  });

  it('B appended AFTER any scan still comes out rebased — the derivation is lazy', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    commitMock.mockReset();
    commitMock.mockImplementationOnce((intent) => Promise.resolve(server.handle(intent) as ProfilePatchOutcome));
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    // A goes out and is fully settled BEFORE B exists. Appends do not take
    // the lock, so no scan run during the acknowledgement could have seen B.
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(server.rev).toBe(2);

    // Now B is written, naming A — whose operation key is already gone.
    const settledA = readRebaseReceipts();
    expect(settledA.ok && settledA.value.size, 'A left a receipt behind').toBeGreaterThan(0);
    const ancestorId = [...(settledA.ok ? settledA.value.keys() : [])][0];
    const b = appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'CS' },
        desired: { present: true, value: 'Physics' },
      }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
      supersedes: [ancestorId],
    }, token)!;
    expect(b).toBeTruthy();

    commitMock.mockReset();
    commitMock.mockImplementation((intent) => Promise.resolve(server.handle(intent) as ProfilePatchOutcome));
    resetProfileDirtyLedger();
    const next = await flushPendingProfileWrite(token);
    expect(next.status).toBe('saved');
    expect(server.seen.at(-1)).toEqual({ expected: 2, patch: { major: 'Physics' } });
  });

  it('a receipt that cannot be written leaves the ancestor outstanding, never half-settled', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const opsBefore = journalOps().map((op) => op.opId);

    const real = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => real.getItem(k),
        setItem: (k: string, v: string) => {
          if (k.includes('journal_v1_rebase_')) throw new Error('quota');
          real.setItem(k, v);
        },
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 2));
    let result;
    try {
      result = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }

    // An ancestor deleted without its receipt is one no descendant can ever
    // rebase onto — so it is not deleted. Reported as a local failure with the
    // work still there to retry.
    expect(result.status).toBe('device-failed');
    expect(journalOps().map((op) => op.opId), 'A is still outstanding').toEqual(opsBefore);
  });

  it('receipts are BOUNDED and the coordinator fails closed at the cap — no silent loss', async () => {
    // Interim contract, and the reason this slice is not done: receipts can
    // only be dropped by a compactor that is fenced against lock-free appends,
    // which is the shared journal lease. Until that exists they accumulate,
    // and reaching the bound must STOP saving visibly rather than quietly
    // delete an acknowledgement a descendant still needs.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    commitMock.mockReset();
    commitMock.mockImplementation((intent) => Promise.resolve(server.handle(intent) as ProfilePatchOutcome));

    // Seed the store right up to the bound, then drive REAL saves into it.
    for (let i = 0; i < 499; i += 1) {
      localStorage.setItem(
        `${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}rebase_seed-${i}`,
        JSON.stringify({
          v: 1,
          ancestorOpId: `seed-${i}`,
          ancestorLineage: 'seed-lineage',
          revision: 1,
          profile: { major: { present: true, value: 'CS' } },
          confirmedKeys: ['major'],
        }),
      );
    }

    let landed = 0;
    let stopped: ProfileSaveResult | null = null;
    for (let i = 0; i < 6; i += 1) {
      const value = `major-${i}`;
      if (!recordProfileIntent({ ...FULL, major: value }, ['major'], token)) break;
      const result = await stageProfilePatch({ ...FULL, major: value }, ['major'], token);
      if (result.status === 'saved') { landed += 1; continue; }
      stopped = result;
      break;
    }

    // It stops, and it says so. What it must never do is keep going by
    // discarding a receipt.
    expect(landed).toBeGreaterThan(0);
    expect(stopped, 'the bound is reached').not.toBeNull();
    expect(stopped!.status).toBe('device-failed');
    const receipts = readRebaseReceipts();
    expect(receipts.ok, 'and every receipt written is still readable').toBe(true);
  });

  it('a crash between the receipt and the settle never re-sends the ancestor', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const a = journalOps()[0];

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    commitMock.mockReset();
    commitMock.mockImplementation((intent) => Promise.resolve(server.handle(intent) as ProfilePatchOutcome));
    await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    expect(server.rev).toBe(2);

    // Simulate the crash: the receipt is on disk, but A's operation key is
    // put BACK, as it would still be if the process died before the delete.
    localStorage.setItem(
      `${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${a.opId}`,
      JSON.stringify(a),
    );
    resetProfileDirtyLedger();

    // A already landed. Its receipt says so, and re-sending it would write a
    // value the row holds against a revision that has moved.
    expect(journalOps().some((op) => op.opId === a.opId)).toBe(false);
    commitMock.mockClear();
    const flushed = await flushPendingProfileWrite(token);
    expect(flushed.status).not.toBe('saved');
    expect(commitMock).not.toHaveBeenCalled();
    // …and the receipt is still there for descendants.
    const receipts = readRebaseReceipts();
    expect(receipts.ok && receipts.value.has(a.opId)).toBe(true);
  });

  it('C reaches A\'s receipt through a still-live B', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    let release: (() => void) | undefined;
    commitMock.mockReset();
    commitMock.mockImplementationOnce((intent) => new Promise<ProfilePatchOutcome>((resolve) => {
      release = () => resolve(server.handle(intent) as ProfilePatchOutcome);
    }));
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    // B continues A.
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const b = journalOps().find((op) => (op.supersedes ?? []).length > 0)!;
    // C continues ONLY B — appended explicitly, because the recorder chains
    // against the whole outstanding ancestry and would name A as well. This
    // is the shape that has to work: the link to A exists only through B.
    const c = appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'Math' },
      }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
      supersedes: [b.opId],
      lineage: b.lineage,
    }, token)!;
    release!();
    await inFlight;

    const ops = journalOps();
    const receipts = readRebaseReceipts();
    const live = receipts.ok ? receipts.value : new Map();
    const byId = new Map(ops.map((op) => [op.opId, op]));
    // Nothing C names directly has a receipt: B is still outstanding.
    expect((c.supersedes ?? []).some((id) => live.has(id))).toBe(false);
    const effective = effectiveOpBase(byId.get(c.opId) ?? c, live, byId);
    expect(effective.baseRevision).toBe(2);
    expect(effective.fields[0].base).toEqual({ present: true, value: 'ECE' });
  });

  it('a composite descendant describes ONE revision, confirmed field and unconfirmed alike', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS', grade: 'Junior' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS', grade: 'Junior' }, 1);
    let release: (() => void) | undefined;
    commitMock.mockReset();
    commitMock.mockImplementationOnce((intent) => new Promise<ProfilePatchOutcome>((resolve) => {
      release = () => resolve(server.handle(intent) as ProfilePatchOutcome);
    }));
    expect(recordProfileIntent({ ...FULL, major: 'ECE', grade: 'Junior' }, ['major'], token)).toBe(true);
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE', grade: 'Junior' }, ['major'], token);
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    // One action touching BOTH fields, only one of which the in-flight write
    // will confirm.
    expect(recordProfileIntent(
      { ...FULL, major: 'Physics', grade: 'Senior' }, ['major', 'grade'], token,
    )).toBe(true);
    release!();
    await inFlight;

    const ops = journalOps();
    const composite = ops.find((op) => op.fields.length === 2)!;
    const receipts = readRebaseReceipts();
    const effective = effectiveOpBase(
      composite,
      receipts.ok ? receipts.value : new Map(),
      new Map(ops.map((op) => [op.opId, op])),
    );
    expect(effective.baseRevision).toBe(2);
    // BOTH bases come from the row at revision 2 — the confirmed field and
    // the one that was never sent. A mix would claim a moment that never was.
    const bases = Object.fromEntries(effective.fields.map((f) => [f.key, f.base]));
    expect(bases.major).toEqual({ present: true, value: 'ECE' });
    expect(bases.grade).toEqual({ present: true, value: 'Junior' });
    // The intent is untouched on both.
    const desired = Object.fromEntries(effective.fields.map((f) => [f.key, f.desired]));
    expect(desired.major).toEqual({ present: true, value: 'Physics' });
    expect(desired.grade).toEqual({ present: true, value: 'Senior' });
  });

  it('a FOREIGN lineage\'s opinion is not rebased — that is a real disagreement', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    let release: (() => void) | undefined;
    commitMock.mockReset();
    commitMock.mockImplementationOnce((intent) => new Promise<ProfilePatchOutcome>((resolve) => {
      release = () => resolve(server.handle(intent) as ProfilePatchOutcome);
    }));
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();

    // ANOTHER TAB writes its own independent opinion of the same field. It
    // supersedes nothing of ours and belongs to a different lineage.
    const other = appendJournalOp({
      fields: [{ key: 'major', base: { present: true, value: 'CS' }, desired: { present: true, value: 'Math' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
      originId: 'other-tab-origin',
      lineage: 'other-tab-lineage',
    }, token)!;
    expect(other).toBeTruthy();

    release!();
    await inFlight;

    const survivor = journalOps().find((op) => op.opId === other.opId)!;
    expect(survivor, 'the other tab\'s edit survives').toBeDefined();
    expect(survivor.baseRevision, 'and still says what IT was based on').toBe(1);
    expect(survivor.fields[0].base).toEqual({ present: true, value: 'CS' });
  });
});

describe('narrowing an abandoned operation never revives a field someone else moved on', () => {
  it('Use Cloud keeps the NEWEST value of the safe field, not the one the old action asked for', async () => {
    // O: one action — college 'LAS' (safe) and major 'Physics' (which will
    // collide). Then N changes college again to 'Media' and lands. When the
    // user answers O's collision with "use the other device's version", the
    // part of O that is carried forward must not include a college value that
    // a later edit has already replaced — it would come back, with a higher
    // sequence number, on top of 'Media'.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, college: 'Grainger', major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(
      { ...FULL, college: 'LAS', major: 'Physics' }, ['college', 'major'], token,
    )).toBe(true);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, college: 'Grainger', major: 'ECE' }, 2));
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'LAS', major: 'ECE' }, 3));
    expect((await stageProfilePatch(
      { ...FULL, college: 'LAS', major: 'Physics' }, ['college', 'major'], token,
    )).status).toBe('conflict');

    // N: the safe field moves on, and lands.
    expect(recordProfileIntent({ ...FULL, college: 'Media', major: 'Physics' }, ['college'], token)).toBe(true);
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'Media', major: 'ECE' }, 4));
    expect((await stageProfilePatch(
      { ...FULL, college: 'Media', major: 'Physics' }, ['college'], token,
    )).status).toBe('conflict');

    // The user takes the other device's major.
    commitMock.mockReset();
    await answerConflict(['major'], 'cloud', token);

    // Nothing is left that wants the old college back…
    // "Asking" is what a READER concludes, not what bytes remain: the
    // replaced operation may still be on disk awaiting cleanup, but nothing
    // may still resolve `college` to the value that was replaced.
    expect(rawMirror()?.college).toBe('Media');
    startDocumentForTests('other');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, college: 'Media', major: 'ECE' }, 4));
    const reread = await hydrateProfile();
    expect(reread.profile?.college, 'the replaced value must not come back').toBe('Media');
    expect(reread.conflictKeys).toEqual([]);

    // …and a flush afterwards has nothing to say about it. The endpoint is
    // given a coherent answer for any call it does make, so an unexpected
    // request shows up as an assertion below rather than as a crash.
    commitMock.mockReset();
    commitMock.mockResolvedValue(saved({ ...FULL, college: 'Media', major: 'ECE' }, 5));
    await flushPendingProfileWrite(token);
    // Whatever it sends, it may never send the value that was replaced. A
    // repeat of the CURRENT value is harmless (the server answers
    // 'unchanged'); the old one would be an overwrite.
    for (const call of commitMock.mock.calls) {
      const patch = call[0].patch as { college?: unknown };
      if ('college' in patch) expect(patch.college).toBe('Media');
    }
    expect(rawMirror()?.college).toBe('Media');
  });
});

describe('an operation is settled only when EVERY field it carries has landed', () => {
  it('a composite edit whose second field collides is not acknowledged by the first field landing', async () => {
    // One action, two fields: switching college clears the major. That is a
    // single journal operation — it either happened or it did not.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, college: 'Grainger', major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(
      { ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token,
    )).toBe(true);
    const [composite] = journalOps();
    expect(composite.fields.map((f) => f.key).sort()).toEqual(['college', 'major']);

    // Another device changed the major in the meantime. `college` is still
    // safe to apply; `major` is a real disagreement and locks.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, college: 'Grainger', major: 'ECE' }, 2));
    commitMock.mockResolvedValueOnce(saved({ ...FULL, college: 'LAS', major: 'ECE' }, 3));
    const result = await stageProfilePatch(
      { ...FULL, college: 'LAS', major: '' }, ['college', 'major'], token,
    );

    expect(result.status).toBe('conflict');
    // The safe half did land…
    expect(commitMock.mock.calls.at(-1)?.[0].patch).toEqual({ college: 'LAS' });
    // …but the operation ALSO asked for `major: ''`, and that never reached
    // the server. Deleting it here would throw that half of the user's action
    // away with no record it ever existed.
    const after = journalOps();
    expect(after.map((op) => op.opId)).toContain(composite.opId);
    const still = after.find((op) => op.opId === composite.opId)!;
    expect(still.fields.find((f) => f.key === 'major')?.desired)
      .toEqual({ present: true, value: '' });
  });
});


describe('a conflict is answered by a durable receipt, not by a special case', () => {
  /** Two tabs, one field, two different values: a local conflict that sends
   *  nothing until the user decides. Returns both operation ids. */
  async function twoOriginConflict(token: ReturnType<typeof captureOwnerToken>) {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    resetJournalLaneForTests();          // a genuinely separate tab
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const ops = journalOps();
    expect(ops).toHaveLength(2);
    commitMock.mockReset();
    const attempt = await stageProfilePatch({ ...FULL, major: 'Physics' }, ['major'], token);
    expect(attempt.status).toBe('conflict');
    expect(commitMock).not.toHaveBeenCalled();
    return ops;
  }

  it('Keep Mine across lineages sends the chosen value exactly once and clears the disagreement', async () => {
    const token = captureOwnerToken();
    await twoOriginConflict(token);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'Physics' }, 8));
    const resolved = await answerConflict(['major'], 'local', token);

    expect(resolved.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'Physics' });
    expect(journalOps()).toEqual([]);
    expect(rawMirror()?.major).toBe('Physics');

    // Reload: nothing comes back, and nothing is re-sent.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    const after = await hydrateProfile();
    expect(after.conflictKeys).toEqual([]);
    expect(after.profile?.major).toBe('Physics');
    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('Use Cloud across lineages costs ZERO requests and both edits stop asking', async () => {
    const token = captureOwnerToken();
    await twoOriginConflict(token);

    commitMock.mockReset();
    const resolved = await answerConflict(['major'], 'cloud', token);

    expect(commitMock).not.toHaveBeenCalled();
    expect(['already-saved', 'saved']).toContain(resolved.status);
    expect(rawMirror()?.major).toBe('CS');
    expect(journalOps().flatMap((op) => op.fields).some((f) => f.key === 'major'
      && f.desired.present && f.desired.value !== 'CS')).toBe(false);

    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const after = await hydrateProfile();
    expect(after.conflictKeys).toEqual([]);
    expect(after.profile?.major).toBe('CS');
    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('resolves from the JOURNAL alone — a crash before staging leaves no outbox to read', async () => {
    const token = captureOwnerToken();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    resetJournalLaneForTests();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);

    // The tab dies before anything is staged: no pending, module memory gone.
    localStorage.removeItem(STORAGE_KEYS.PROFILE_SYNC);
    startDocumentForTests('other');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const hydrated = await hydrateProfile();
    expect(hydrated.conflictKeys).toEqual(['major']);
    expect(readProfileSyncEnvelope()?.pending ?? null).toBeNull();

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 8));
    // This document owns neither value — both tabs are gone — so the answer
    // has to say which one is on screen.
    const resolved = await answerConflict(
      ['major'], 'local', token, { ...FULL, major: 'ECE' },
    );
    expect(resolved.status).toBe('saved');
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'ECE' });
    expect(journalOps()).toEqual([]);
  });

  it('two fields answered one after the other each stick, and neither revives the other', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS', college: 'Grainger' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(
      { ...FULL, major: 'ECE', college: 'LAS' }, ['major', 'college'], token,
    )).toBe(true);
    resetJournalLaneForTests();
    expect(recordProfileIntent(
      { ...FULL, major: 'Physics', college: 'Media' }, ['major', 'college'], token,
    )).toBe(true);

    commitMock.mockReset();
    expect((await stageProfilePatch(
      { ...FULL, major: 'Physics', college: 'Media' }, ['major', 'college'], token,
    )).status).toBe('conflict');
    expect(commitMock).not.toHaveBeenCalled();

    // First answer: take the cloud's major.
    commitMock.mockReset();
    await answerConflict(['major'], 'cloud', token);
    expect(commitMock).not.toHaveBeenCalled();

    // Second answer: keep this device's college.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'CS', college: 'Media' }, 8));
    const second = await answerConflict(['college'], 'local', token);
    expect(second.status).toBe('saved');
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ college: 'Media' });

    // The first answer is not undone by the second.
    expect(rawMirror()?.major).toBe('CS');
    expect(rawMirror()?.college).toBe('Media');
    expect(journalOps()).toEqual([]);
  });

  it('a crash after the receipt but before cleanup still answers the conflict', async () => {
    const token = captureOwnerToken();
    await twoOriginConflict(token);

    // The answer is recorded, and then nothing else finishes: the send does
    // not land, so the operations it answers are never cleaned up. This is
    // what a crash between the two looks like on disk.
    commitMock.mockReset();
    commitMock.mockResolvedValue({ status: 'transport-error', message: 'offline' });
    await answerConflict(['major'], 'local', token);
    expect(journalOps().length, 'the receipt and what it answers are all still here')
      .toBeGreaterThan(1);

    // A fresh document reads them and must see an ANSWERED conflict, not a
    // live one — the receipt is the decision, cleanup is housekeeping.
    startDocumentForTests('other');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const after = await hydrateProfile();
    expect(after.conflictKeys, 'the receipt answers it; the leftovers do not re-raise it')
      .toEqual([]);
    expect(after.profile?.major).toBe('Physics');

    // …and the answer is still owed to the server, exactly once.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'Physics' }, 8));
    const drained = await flushPendingProfileWrite(token);
    expect(drained.status).toBe('saved');
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'Physics' });
    expect(journalOps()).toEqual([]);
  });
});


describe('an answer covers the disagreement that was SHOWN, and nothing else', () => {
  it('an edit that arrives while the question is open makes the answer STALE — nothing is consumed, nothing is sent', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    resetJournalLaneForTests();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);

    // What the person is looking at, captured when the conflict was rendered.
    const shown = await hydrateProfile();
    expect(shown.conflictKeys).toEqual(['major']);
    const snapshot = shown.conflicts.find((c) => c.key === 'major')!;
    expect(snapshot.candidates.map((v) => v.value).sort()).toEqual(['ECE', 'Physics']);

    // A THIRD tab types something while the dialog is open.
    resetJournalLaneForTests();
    expect(recordProfileIntent({ ...FULL, major: 'Statistics' }, ['major'], token)).toBe(true);

    // The person picks ECE — out of the two candidates they were shown. But
    // the question is no longer a two-way disagreement, and an answer to the
    // question that WAS on screen is not an answer to the one that is. It
    // does not get to settle a candidate nobody was shown, and it does not
    // get to become a clean patch over it either.
    commitMock.mockReset();
    const answered = await answerConflict(
      ['major'], 'local', token, { ...FULL, major: 'ECE' }, [snapshot],
    );
    expect(answered.status).toBe('stale-conflict');
    expect(commitMock, 'nothing is sent').not.toHaveBeenCalled();
    expect(
      journalOps().find((op) => op.mode === 'resolve'),
      'and nothing is recorded: a receipt here would answer for the third tab',
    ).toBeUndefined();

    // A fresh reader sees the disagreement intact — all three candidates,
    // none of them decided.
    startDocumentForTests('other');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const after = await hydrateProfile();
    expect(after.conflictKeys).toEqual(['major']);
    const still = after.conflicts.find((c) => c.key === 'major')!;
    expect(still.candidates.map((c) => c.value).sort())
      .toEqual(['ECE', 'Physics', 'Statistics']);
  });

  it('answering one of two locked fields reports the remaining one, with its candidates', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS', grade: 'Junior' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(
      { ...FULL, major: 'Physics', grade: 'Senior' }, ['major', 'grade'], token,
    )).toBe(true);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, major: 'ECE', grade: 'Masters' }, 2));
    const first = await stageProfilePatch(
      { ...FULL, major: 'Physics', grade: 'Senior' }, ['major', 'grade'], token,
    );
    expect(first.status).toBe('conflict');
    const asked = (first as { conflicts: ProfileConflict[] }).conflicts;
    expect(asked.map((c) => c.key).sort()).toEqual(['grade', 'major']);
    // Even a server collision says what is in dispute and which operations
    // are behind this device's value.
    const majorAsked = asked.find((c) => c.key === 'major')!;
    expect(majorAsked.remote).toBe('ECE');
    expect(majorAsked.candidates[0].value).toBe('Physics');
    expect(majorAsked.candidates[0].opIds.length).toBeGreaterThan(0);

    // Answer ONE of them with the other device's value.
    commitMock.mockReset();
    const partial = await answerConflict(
      ['major'], 'cloud', token, undefined, [majorAsked],
    );

    // Not "saved": `grade` is still in dispute, and the screen must keep
    // asking about it.
    expect(partial.status).toBe('conflict');
    const remaining = (partial as { conflicts: ProfileConflict[] }).conflicts;
    expect(remaining.map((c) => c.key)).toEqual(['grade']);
    expect(remaining[0].candidates[0].value).toBe('Senior');
    expect(remaining[0].remote).toBe('Masters');
  });
});


describe('a row the cloud says is gone is never quietly recreated', () => {
  it('a deleted row fences the flush until someone explicitly asks for it back', async () => {
    // The account had a row and an unsent edit; the cloud now says there is
    // no row. That is a deletion, not a blank slate — sending the working
    // copy as a create would put the deleted profile straight back.
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    loadProfileMock.mockResolvedValue(absent());
    const gone = await hydrateProfile();
    expect(gone.profile, 'nothing of the dead row is served').toBeNull();
    const tombstone = readProfileSyncEnvelope()?.tombstone;
    expect(tombstone?.reason).toBe('deleted');

    commitMock.mockReset();
    const flushed = await flushPendingProfileWrite(token);
    expect(commitMock, 'a deleted row is not recreated behind the user').not.toHaveBeenCalled();
    expect(['blocked', 'stale', 'missing']).toContain(flushed.status);

    // …and it stays fenced across a reload, with no outbox left to fire.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(absent());
    const again = await hydrateProfile();
    expect(readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
    expect(again.profile).toBeNull();
    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('a SECOND absent load does not unfence what the first one tombstoned', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 4));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    loadProfileMock.mockResolvedValue(absent());
    await hydrateProfile();
    await hydrateProfile(); // the second one is where the fence used to lift

    expect(readProfileSyncEnvelope()?.tombstone?.reason).toBe('deleted');
    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock).not.toHaveBeenCalled();
  });
});


describe('a slow answer never rolls the browser backwards', () => {
  it('an absence captured before another tab created the row does not erase it', async () => {
    // This read was issued when there genuinely was no row. While it was in
    // flight, another tab created one at revision 1. Applying the stale
    // answer now would erase that row locally and tombstone an account that
    // very much exists.
    const token = captureOwnerToken();
    let settleAbsent: (() => void) | undefined;
    loadProfileMock.mockImplementation(() => new Promise<LoadedProfile>((resolve) => {
      settleAbsent = () => resolve(absent());
    }));
    const slow = hydrateProfile();
    for (let i = 0; i < 50 && !settleAbsent; i += 1) await Promise.resolve();
    expect(settleAbsent).toBeDefined();

    // The other tab's creation lands here first.
    loadProfileMock.mockResolvedValue(cloud(FULL, 1));
    await hydrateProfile();
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(1);

    settleAbsent!();
    const stale = await slow;

    expect(readProfileSyncEnvelope()?.confirmed?.revision, 'the row still exists').toBe(1);
    expect(readProfileSyncEnvelope()?.tombstone ?? null).toBeNull();
    expect(rawMirror()).toEqual(FULL);
    expect(stale.revision, 'and the caller is told what is actually there').toBe(1);
    expect(stale.profile).toEqual(FULL);

    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock).not.toHaveBeenCalled();
  });
});


describe('a local-only repair does not overwrite what another tab staged meanwhile', () => {
  it('replaying an OLDER unwritten confirmation leaves every newer record alone', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    // The cloud takes revision 8; recording it locally fails, so a repair is
    // owed for revision 8 and nothing else.
    const real = window.localStorage;
    // Blocked only AFTER the send lands: blocking earlier would fail the
    // stage before anything was ever confirmed, and no repair would be owed
    // at all — which is how this test used to pass without testing anything.
    let blockEnvelope = false;
    const cells = new Map<string, string>();
    for (let i = 0; i < real.length; i += 1) cells.set(real.key(i)!, real.getItem(real.key(i)!)!);
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => (cells.has(k) ? cells.get(k)! : null),
        removeItem: (k: string) => { cells.delete(k); },
        setItem: (k: string, v: string) => {
          if (blockEnvelope && k === STORAGE_KEYS.PROFILE_SYNC) throw new Error('QuotaExceededError');
          cells.set(k, v);
        },
        clear: () => cells.clear(),
        key: (i: number) => [...cells.keys()][i] ?? null,
        get length() { return cells.size; },
      },
    });
    let half: Awaited<ReturnType<typeof stageProfilePatch>>;
    try {
      commitMock.mockReset();
      commitMock.mockImplementationOnce(async () => {
        blockEnvelope = true;
        return saved({ ...FULL, major: 'ECE' }, 8);
      });
      half = await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    } finally {
      blockEnvelope = false;
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
      for (const [k, v] of cells) real.setItem(k, v);
    }
    expect(half!.status).toBe('device-failed');
    expect((half as { phase?: string }).phase, 'the cloud took it; only the record failed')
      .toBe('confirm');

    // Another tab moves the world on: a NEWER confirmed revision, a newer raw
    // mirror, and a newer outbox entry of its own.
    const newerRow = { ...FULL, major: 'ECE', grade: 'Senior', research_interests: 'newer' };
    // Written as bytes, the way the other tab's process would have left them.
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: { revision: 12, profile: newerRow },
      pending: null,
      tombstone: null,
    }));
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify(newerRow));
    expect(readProfileSyncEnvelope()?.confirmed?.revision).toBe(12);
    // Deliberately NO second stage here: a successful one would clear the
    // owed repair, and the guard under test would never be reached.
    const before = {
      revision: readProfileSyncEnvelope()!.confirmed!.revision,
      mirror: rawMirror(),
    };
    expect(before.revision).toBeGreaterThanOrEqual(12);

    // Now the owed repair for revision 8 runs. Everything it touches must
    // stay at least as new as it already is.
    commitMock.mockReset();
    const repaired = await flushPendingProfileWrite(token);
    expect(commitMock, 'a local repair never goes near the network').not.toHaveBeenCalled();

    const after = readProfileSyncEnvelope()!;
    expect(after.confirmed!.revision, 'the envelope does not go backwards')
      .toBeGreaterThanOrEqual(before.revision);
    expect(after.confirmed!.profile.research_interests, 'nor does its content').toBe('newer');
    expect(rawMirror()!.research_interests, 'nor the mirror every screen reads').toBe('newer');
    if (repaired.status === 'already-saved') {
      expect(repaired.revision, 'nor what the caller is told')
        .toBeGreaterThanOrEqual(before.revision);
    }
  });
});


describe('a conflict response decides from the outbox as it is, not as it was', () => {
  it("does not roll back an edit another tab staged while the response was in flight", async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);

    // The other tab's own edit, made durable the way it really would be.
    resetJournalLaneForTests();
    expect(recordProfileIntent({ ...FULL, grade: 'Senior' }, ['grade'], token)).toBe(true);
    const otherTabOp = journalOps().find((o) => o.fields.some((f) => f.key === 'grade'))!;
    expect(otherTabOp).toBeDefined();

    // Its outbox entry appears in the window that matters: after this
    // response has read the outbox, while it is waiting for the lock. Hooking
    // the lock itself is the only way to land inside that gap.
    let injectOnce: (() => void) | null = null;
    const locks = navigator.locks as unknown as {
      request: (n: string, o: unknown, fn: () => Promise<unknown>) => Promise<unknown>;
    };
    const realRequest = locks.request;
    locks.request = (n: string, o: unknown, fn: () => Promise<unknown>) => realRequest(n, o, () => {
      const inject = injectOnce;
      injectOnce = null;
      inject?.();
      return fn();
    });

    const stageTheOtherTab = () => {
      // Taken from what is on disk right now, so the shape is exactly what the
      // coordinator itself writes — only the fields that identify it as a
      // NEWER, different write are changed.
      const live = JSON.parse(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC)!);
      live.pending = {
        ...live.pending,
        mutationId: 'staged-by-the-other-tab',
        desiredProfile: { ...live.pending.desiredProfile, grade: 'Senior' },
        dirtyKeys: ['grade'],
        lockedKeys: [],
        journalOpIds: [otherTabOp.opId],
        journalPlan: { grade: [otherTabOp.opId] },
      };
      localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify(live));
      localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ ...FULL, grade: 'Senior' }));
    };

    commitMock.mockReset();
    commitMock.mockImplementationOnce(async () => {
      injectOnce = stageTheOtherTab; // fires when the response takes the lock
      return conflict({ ...FULL, major: 'Physics' }, 8);
    });

    try {
      await stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    } finally {
      locks.request = realRequest;
    }

    // The coordinator may repackage the entry — a new mutation id is its own
    // business. What may NOT happen is the older captured snapshot putting
    // any of the newer tab's work back.
    const env = readProfileSyncEnvelope();
    expect(env?.confirmed?.revision, 'the revision never goes backwards')
      .toBeGreaterThanOrEqual(8);
    const pending = env?.pending;
    expect(pending, 'the newer tab still has an entry').toBeTruthy();
    expect(pending!.desiredProfile.grade, "its value is not reverted").toBe('Senior');
    expect(pending!.dirtyKeys, 'its field is still unsent').toContain('grade');
    expect(pending!.journalOpIds, 'and it still points at its own durable evidence')
      .toContain(otherTabOp.opId);
    expect(rawMirror()?.grade, 'as does the copy every screen reads').toBe('Senior');
    // The stale snapshot's own field must not have been written over it.
    expect(pending!.dirtyKeys).not.toEqual(['major']);
    expect(journalOps().some((o) => o.opId === otherTabOp.opId),
      "the other tab's operation is not consumed by this response").toBe(true);
  });
});


describe('creating a row requires a profile that MEANS something', () => {
  const skeleton = { ...FULL, college: '   ', major: '\t', grade: '', search_weight: 'lots' };

  it('a create whose required fields are blank or nonsense is refused locally, with no request', async () => {
    loadProfileMock.mockResolvedValue(absent());
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(skeleton as unknown as ProfileData,
      ['college', 'major', 'grade', 'search_weight'], token)).toBe(true);

    commitMock.mockReset();
    const attempt = await stageProfilePatch(
      skeleton as unknown as ProfileData,
      ['college', 'major', 'grade', 'search_weight'],
      token,
      { allowCreate: true },
    );

    // The server would reject it; saying so here is the same answer without
    // the round trip — and without a row that exists but says nothing.
    expect(commitMock, 'a row is never created from a blank form').not.toHaveBeenCalled();
    expect(['blocked', 'staged-local']).toContain(attempt.status);
  });

  it('a create with real values still goes', async () => {
    loadProfileMock.mockResolvedValue(absent());
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent(FULL, ['college', 'major', 'grade', 'search_weight'], token)).toBe(true);
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved(FULL, 1));
    const created = await stageProfilePatch(
      FULL, ['college', 'major', 'grade', 'search_weight'], token, { allowCreate: true },
    );
    expect(created.status).toBe('saved');
  });
});


describe('every writer goes through one durable action', () => {
  it('records the intent BEFORE anything is sent, and sends nothing if it cannot', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 3));
    const token = captureOwnerToken();
    await hydrateProfile();

    // Storage refuses. The action must report that plainly and go nowhere
    // near the network: a write nobody recorded is a write nobody can retry.
    const real = window.localStorage;
    const cells = new Map<string, string>();
    for (let i = 0; i < real.length; i += 1) cells.set(real.key(i)!, real.getItem(real.key(i)!)!);
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => (cells.has(k) ? cells.get(k)! : null),
        removeItem: (k: string) => { cells.delete(k); },
        setItem: () => { throw new Error('QuotaExceededError'); },
        clear: () => cells.clear(),
        key: (i: number) => [...cells.keys()][i] ?? null,
        get length() { return cells.size; },
      },
    });
    commitMock.mockReset();
    let blocked: Awaited<ReturnType<typeof commitProfileAction>>;
    try {
      blocked = await commitProfileAction({
        keys: ['include_cross_school'],
        view: viewOf(FULL, 3, token),
        desiredAfter: { ...FULL, include_cross_school: true } as unknown as ProfileData,
        writer: 'results',
      });
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }
    expect(blocked!.durable, 'the caller is told the edit was not recorded').toBe(false);
    expect(commitMock, 'and nothing was sent').not.toHaveBeenCalled();

    // With storage working, the same action records first and then sends.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, include_cross_school: true }, 4));
    const ok = await commitProfileAction({
      keys: ['include_cross_school'],
      view: viewOf(FULL, 3, token),
      desiredAfter: { ...FULL, include_cross_school: true } as unknown as ProfileData,
      writer: 'results',
    });
    expect(ok.durable).toBe(true);
    expect(ok.result?.status).toBe('saved');
    expect(commitMock.mock.calls[0][0].patch).toEqual({ include_cross_school: true });
  });

  it('an action that cannot be recorded leaves nothing behind to replay', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 3));
    const token = captureOwnerToken();
    await hydrateProfile();
    const before = journalOps().length;

    const real = window.localStorage;
    const cells = new Map<string, string>();
    for (let i = 0; i < real.length; i += 1) cells.set(real.key(i)!, real.getItem(real.key(i)!)!);
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => (cells.has(k) ? cells.get(k)! : null),
        removeItem: (k: string) => { cells.delete(k); },
        setItem: () => { throw new Error('QuotaExceededError'); },
        clear: () => cells.clear(),
        key: (i: number) => [...cells.keys()][i] ?? null,
        get length() { return cells.size; },
      },
    });
    try {
      const blocked = await commitProfileAction({
        keys: ['research_interests'],
        view: viewOf(FULL, 3, token),
        desiredAfter: { ...FULL, research_interests: 'x' },
        writer: 'home-form',
      });
      expect(blocked.durable).toBe(false);
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }
    expect(journalOps().length, 'no half-written operation is left').toBe(before);
  });
});


describe('a view snapshot survives a browser without structuredClone', () => {
  it('still severs aliases, still freezes, and still tells absence apart from own-undefined', () => {
    const original = globalThis.structuredClone;
    // @ts-expect-error deliberately removing the global to exercise the floor
    globalThis.structuredClone = undefined;
    try {
      const owner = captureOwnerToken();
      const base = {
        ...FULL,
        skills: [{ name: 'Rust', level: 'expert' as const }],
        // A key that EXISTS and holds undefined. A JSON round-trip deletes
        // it, which is the difference between "set to nothing" and "never
        // had this field" — and the whole point of the baseline.
        home_school: undefined,
      } as ProfileData;
      const absent = { ...FULL } as Record<string, unknown>;
      delete absent.home_school;

      const withUndefined = makeProfileViewSnapshot({
        baseProfile: base,
        renderedProfile: base,
        revision: 5,
        token: owner,
        identityGeneration: owner.epoch,
        source: 'hydration',
      });
      const withAbsent = makeProfileViewSnapshot({
        baseProfile: absent as unknown as ProfileData,
        renderedProfile: base,
        revision: 5,
        token: owner,
        identityGeneration: owner.epoch,
        source: 'hydration',
      });

      expect(Object.hasOwn(withUndefined.baseProfile as object, 'home_school')).toBe(true);
      expect(withUndefined.baseProfile!.home_school).toBeUndefined();
      expect(Object.hasOwn(withAbsent.baseProfile as object, 'home_school')).toBe(false);

      // Nested structures are copies, not aliases.
      base.skills[0].level = 'beginner';
      base.skills.push({ name: 'Go', level: 'beginner' });
      expect(withUndefined.baseProfile!.skills).toEqual([{ name: 'Rust', level: 'expert' }]);

      // Frozen all the way down; the caller's own objects untouched.
      expect(Object.isFrozen(withUndefined.baseProfile!.skills[0])).toBe(true);
      expect(Object.isFrozen(withUndefined.token)).toBe(true);
      expect(Object.isFrozen(base)).toBe(false);
      expect(Object.isFrozen(owner)).toBe(false);
    } finally {
      globalThis.structuredClone = original;
    }
  });
});

describe('an answer that arrives after the row was deleted does not resurrect it', () => {
  it('a slow revision-7 row landing after another tab wrote the fence is not adopted', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();

    // The next read is issued, and while it is in flight another tab is told
    // the row is gone and writes the fence. `confirmed` is null now, so a
    // revision comparison sees nothing to beat.
    let release: ((v: LoadedProfile) => void) | undefined;
    loadProfileMock.mockImplementationOnce(() => new Promise<LoadedProfile>((resolve) => {
      release = resolve;
    }));
    const inFlight = hydrateProfile();
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: null,
      pending: null,
      tombstone: { reason: 'deleted', rawQuarantined: true },
    }));

    release!({ source: 'cloud', profile: { ...FULL, major: 'CS' }, revision: 7, token });
    const hydration = await inFlight;

    expect(hydration.profile, 'nothing of the dead row is shown').toBeNull();
    expect(hydration.baseProfile).toBeNull();
    expect(readProfileSyncEnvelope()?.tombstone?.reason, 'the fence stands').toBe('deleted');
    expect(readProfileSyncEnvelope()?.confirmed, 'and the row is not back').toBeFalsy();
  });

  it('an unfinished quarantine is finished, not reported as clean', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(rawMirror()).toBeTruthy();

    let release: ((v: LoadedProfile) => void) | undefined;
    loadProfileMock.mockImplementationOnce(() => new Promise<LoadedProfile>((resolve) => {
      release = resolve;
    }));
    const inFlight = hydrateProfile();
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    // The other tab wrote the fence but could NOT remove the mirror.
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: null,
      pending: null,
      tombstone: { reason: 'deleted', rawQuarantined: false },
    }));

    release!({ source: 'cloud', profile: { ...FULL, major: 'CS' }, revision: 7, token });
    const hydration = await inFlight;

    // A legacy-readable profile in the slot every other screen reads, under a
    // fence that claims to be complete, is the worst of both.
    expect(hydration.profile).toBeNull();
    expect(rawMirror(), 'the removal was retried under this owner').toBeNull();
    expect(hydration.quarantineFailed).toBe(false);
    expect(readProfileSyncEnvelope()?.tombstone).toEqual({ reason: 'deleted', rawQuarantined: true });
  });

  it('reports the failure when the mirror still cannot be removed', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();

    let release: ((v: LoadedProfile) => void) | undefined;
    loadProfileMock.mockImplementationOnce(() => new Promise<LoadedProfile>((resolve) => {
      release = resolve;
    }));
    const inFlight = hydrateProfile();
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: null,
      pending: null,
      tombstone: { reason: 'deleted', rawQuarantined: false },
    }));

    const real = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => real.getItem(k),
        setItem: (k: string, v: string) => {
          if (k === STORAGE_KEYS.PROFILE) throw new Error('quota');
          real.setItem(k, v);
        },
        removeItem: (k: string) => {
          if (k === STORAGE_KEYS.PROFILE) throw new Error('quota');
          real.removeItem(k);
        },
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    let hydration;
    try {
      release!({ source: 'cloud', profile: { ...FULL, major: 'CS' }, revision: 7, token });
      hydration = await inFlight;
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }
    expect(hydration.quarantineFailed, 'said out loud, never assumed away').toBe(true);
  });
});

describe('an answer bound to the PENDING write, not to operations', () => {
  /**
   * A PRE-CAS working copy meeting a real cloud row: this browser has a
   * profile it never recorded an operation for (it predates the journal), so
   * the disagreement it raises has no op ids at all. The pending write is the
   * only durable thing behind it.
   */
  async function pendingOnlyConflict(token: OwnerToken) {
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ ...FULL, major: 'ECE' }));
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    const h = await hydrateProfile();
    expect(h.conflictKeys).toEqual(['major']);
    void token;
    const question = readCurrentConflicts(['major'], captureOwnerToken());
    expect(question[0].candidates.every((c) => c.opIds.length === 0),
      'nothing recorded it: there are no operation ids to name').toBe(true);
    expect(question[0].mutationId, 'so the mutation is the identity').toBeTruthy();
    expect(question[0].keyVersion).not.toBeNull();
    return question;
  }

  it('KEEP MINE against a pending-only question sends the chosen value', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const answered = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'local',
      { ...FULL, major: 'ECE' },
    ));

    expect(answered.status).toBe('saved');
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'ECE' });
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(8);
  });

  it('USE CLOUD against a pending-only question applies the value that was SHOWN, with no request', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);

    // The row moves again while the dialog sits open. "Use the other version"
    // means the version they were looking at — and because it is no longer the
    // current question, it is refused outright rather than applied to a value
    // nobody saw.
    commitMock.mockReset();
    const answered = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'cloud',
      { ...FULL, major: 'ECE' },
    ));
    expect(answered.status).toBe('already-saved');
    expect(commitMock, 'the chosen value IS the row: nothing to send').not.toHaveBeenCalled();
    expect(rawMirror()?.major).toBe('Physics');
  });

  it('a second, opposite click on the same pending question writes nothing more', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'local',
      { ...FULL, major: 'ECE' },
    ));
    const receiptsAfterFirst = journalOps().filter((op) => op.mode === 'resolve').length;

    // The other button, on the prompt that is still on screen.
    commitMock.mockReset();
    const second = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'cloud',
      { ...FULL, major: 'ECE' },
    ));
    expect(second.status).toBe('stale-conflict');
    expect(commitMock, 'zero network').not.toHaveBeenCalled();
    expect(journalOps().filter((op) => op.mode === 'resolve').length,
      'zero additional receipt').toBe(receiptsAfterFirst);
  });

  it('a crash after the receipt but before the send is repaired on the next read', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);

    // The receipt lands; the process dies before stageProfilePatch updates
    // the envelope. Written directly so nothing else runs.
    const envelope = readProfileSyncEnvelope()!;
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();
    expect(readProfileSyncEnvelope()!.pending!.lockedKeys,
      'the outbox is still locked — the crash was before the repair').toEqual(['major']);

    // A REAL new document — fresh module globals, fresh origin and lineage,
    // storage untouched — not merely a cleared ledger in the same session.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    await hydrateProfile();
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const flushed = await flushPendingProfileWrite(token);

    expect(flushed.status).toBe('saved');
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'ECE' });
    expect(commitMock.mock.calls[0][0].expectedRevision,
      'against the row the person was shown').toBe(8);
  });

  it('HYDRATE alone repairs the answer — Home never reaches a flush after a conflict', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    // The reload's own read, and nothing else. Home stops here when hydration
    // reports a conflict, so everything the person sees has to be right by
    // the time this returns.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    const hydration = await hydrateProfile();

    expect(hydration.conflictKeys, 'the question is settled').toEqual([]);
    expect(hydration.conflicts).toEqual([]);
    expect(hydration.profile!.major, 'and the answer is what is shown').toBe('ECE');
    expect(readProfileSyncEnvelope()!.pending!.lockedKeys).toEqual([]);
    expect(rawMirror()?.major).toBe('ECE');
  });

  it('answering ONE of two fields leaves the other locked and does not resurrect the answered one', async () => {
    // Two fields in dispute, neither with an operation behind it.
    localStorage.setItem(
      STORAGE_KEYS.PROFILE,
      JSON.stringify({ ...FULL, major: 'ECE', college: 'LAS' }),
    );
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics', college: 'Grainger' }, 8));
    const token = captureOwnerToken();
    const first = await hydrateProfile();
    expect([...first.conflictKeys].sort()).toEqual(['college', 'major']);
    const asked = readCurrentConflicts(['major'], token);
    const envelope = readProfileSyncEnvelope()!;

    // Only `major` is answered.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: asked[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    // Crash, REAL reload, hydrate.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics', college: 'Grainger' }, 8));
    const after = await hydrateProfile();

    // The answered field stays answered — a whole-write `legacy` flag left
    // set would have re-locked it here, resurrecting the disagreement the
    // person just settled.
    expect(after.conflictKeys, 'only the unanswered field is still in dispute')
      .toEqual(['college']);
    expect(after.profile!.major).toBe('ECE');
    const pending = readProfileSyncEnvelope()!.pending!;
    expect(pending.lockedKeys).toEqual(['college']);

    // And the answered field can go out on its own, without the locked one.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE', college: 'Grainger' }, 9));
    const flushed = await flushPendingProfileWrite(token);
    expect(flushed.status).toBe('conflict');
    expect(commitMock.mock.calls[0][0].patch, 'the locked field is not in the patch')
      .toEqual({ major: 'ECE' });
  });

  it('a MIXED receipt: the tuple-bound key is excluded, the op-backed key is not', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS', college: 'Grainger' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(recordProfileIntent({ ...FULL, college: 'LAS' }, ['college'], token)).toBe(true);
    const collegeOp = journalOps().find((op) => op.fields.some((f) => f.key === 'college'))!;

    // One receipt answering BOTH: `college` through the operation it names,
    // `major` through a pending instance that has since gone stale.
    expect(appendJournalOp({
      fields: [
        { key: 'college', base: { present: true, value: 'Grainger' }, desired: { present: true, value: 'LAS' } },
        { key: 'major', base: { present: true, value: 'Physics' }, desired: { present: true, value: 'ECE' } },
      ],
      baseRevision: 7,
      writer: 'default',
      mode: 'resolve',
      resolves: [collegeOp.opId],
      resolvesPending: { mutationId: 'gone-mutation', keyVersions: { major: 1 } },
      decisions: { college: 'local', major: 'local' },
    }, token)).toBeTruthy();

    const ops = journalOps();
    const plan = planKeysFromJournalForTests(ops, ['college', 'major']);

    // `college` keeps its resolved-op semantics — a blanket skip would drop
    // the answer entirely and re-ask a question the person already settled.
    expect(plan.get('college')?.kind).toBe('value');
    const collegePlan = plan.get('college');
    expect(collegePlan?.kind === 'value' && collegePlan.value).toBe('LAS');
    // `major` is tuple-bound and its tuple is stale: it contributes nothing.
    expect(plan.get('major'), 'the stale half never becomes a generic edit').toBeUndefined();
  });

  it("an old tab's opposite click after another tab already answered writes nothing", async () => {
    const token = captureOwnerToken();
    // TAB A renders the question and keeps it.
    const aPrompt = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    // TAB B answers it — Keep Mine — and the repair applies, which clears the
    // last lock AND the conflict snapshot.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: aPrompt[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();
    // The repair takes the last lock off a write the cloud does not have yet,
    // so the refresh finishes it — which is what B's answer actually landing
    // looks like from this tab.
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    expect((await refreshConflictQuestion(['major'], token)).status).toBe('settled');
    expect(readProfileSyncEnvelope()!.pending?.lockedKeys ?? []).toEqual([]);
    expect(readProfileSyncEnvelope()!.pending?.conflictRemote ?? null).toBeNull();

    const receiptsBefore = journalOps().filter((op) => op.mode === 'resolve').length;
    const envelopeBefore = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    const mirrorBefore = localStorage.getItem(STORAGE_KEYS.PROFILE);

    // TAB A now clicks the OPPOSITE button on its retained prompt. A matcher
    // that judged the cleared current state would no longer recognise B's
    // receipt, accept this, and overwrite the answer.
    commitMock.mockReset();
    const second = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      aPrompt,
      'cloud',
      { ...FULL, major: 'ECE' },
    ));

    expect(second.status).toBe('stale-conflict');
    expect(commitMock, 'zero network').not.toHaveBeenCalled();
    expect(journalOps().filter((op) => op.mode === 'resolve').length,
      'zero new receipt').toBe(receiptsBefore);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC), 'zero storage mutation')
      .toBe(envelopeBefore);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(mirrorBefore);

    // And B's answer survives a REAL reload.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    const after = await hydrateProfile();
    expect(after.profile!.major, "B's answer stands").toBe('ECE');
    expect(after.conflictKeys).toEqual([]);
  });

  it('an old receipt does not make a genuinely NEW question stale', async () => {
    const token = captureOwnerToken();
    const old = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    // A receipt about the rev8 question.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: old[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    // The SAME pending write is rebased onto a newer row: same mutation id,
    // advanced revision and field version. Only the receipt's own recorded
    // revision and version tell this question apart from the one it answered.
    const rebased = {
      ...envelope,
      confirmed: { revision: 9, profile: { ...FULL, major: 'Statistics' } },
      pending: {
        ...envelope.pending!,
        baseRevision: 9,
        keyVersions: { ...envelope.pending!.keyVersions, major: old[0].keyVersion! + 1 },
        conflictRemote: { ...FULL, major: 'Statistics' },
      },
    };
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify(rebased));
    resetProfileDirtyLedger();
    const current = readCurrentConflicts(['major'], token);
    expect(current[0].remoteRevision, 'a new question').toBe(9);
    expect(current[0].mutationId, 'on the SAME mutation').toBe(envelope.pending!.mutationId);

    // Answering the CURRENT question must work. A guard that compared only
    // the mutation id would let the rev8 receipt declare this one answered,
    // and it could never be settled.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 10));
    const answered = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 9, token),
      current,
      'local',
      { ...FULL, major: 'ECE' },
    ));
    expect(answered.status, 'the new question closes').not.toBe('stale-conflict');
  });

  it('a receipt for a DIFFERENT outbox entry with identical numbers is not this answer', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);

    // Same field version, same revision, same shown row — and a mutation id
    // from an outbox entry that is gone. Everything the canonical matcher
    // compares agrees EXCEPT the one thing that says which write this answer
    // belongs to.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: `${question[0].mutationId!}-superseded`,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    // It answers nothing here: the current question is still open, and the
    // person's real click on it goes through.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const answered = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'local',
      { ...FULL, major: 'ECE' },
    ));
    expect(answered.status, 'another write\'s answer cannot settle this one').toBe('saved');

    // And it was never applied to this write either — the lock came off
    // because the person answered, not because a foreign receipt unlocked it.
    expect(commitMock.mock.calls[0][0].patch).toEqual({ major: 'ECE' });
  });

  it('Use Cloud whose envelope write fails keeps the proof, and a reload never re-asks', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);

    // The envelope write fails while the answer is being applied. There is no
    // network on this path, so the receipt is the ONLY durable proof.
    const real = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => real.getItem(k),
        setItem: (k: string, v: string) => {
          if (k === STORAGE_KEYS.PROFILE_SYNC) throw new Error('quota');
          real.setItem(k, v);
        },
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    commitMock.mockReset();
    let answered;
    try {
      answered = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'cloud',
      { ...FULL, major: 'ECE' },
    ));
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }

    expect(answered.status, 'reported, not silently swallowed').toBe('device-failed');
    expect(commitMock, 'no network on this path at all').not.toHaveBeenCalled();
    expect(journalOps().some((op) => op.mode === 'resolve'),
      'the proof survives the failure — settling it first would lose the answer').toBe(true);

    // Storage recovers, a REAL reload happens: the answer is applied and the
    // question is never asked again.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    const after = await hydrateProfile();
    expect(after.conflictKeys, 'never re-asked').toEqual([]);
    expect(after.profile!.major, "and the cloud value the person chose is what shows").toBe('Physics');
  });

  it('a receipt with the right numbers but the WRONG base never blocks a real answer', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    // Same mutation, same key version, same revision — but its recorded base
    // is not the row this question is about. Application refuses it, so a
    // staleness check that compared only the numbers would call it an answer
    // and the person could never get past the prompt.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'SomethingElse' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const answered = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'local',
      { ...FULL, major: 'ECE' },
    ));

    expect(answered.status, 'the real answer goes through').toBe('saved');
    expect(readProfileSyncEnvelope()!.pending?.lockedKeys ?? []).toEqual([]);
  });

  it('a stale rev8 receipt never blocks the rev9 question — cloud answer', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    // A rev8 answer that the tab never delivered.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    // The row moves to rev9. The stale receipt is correctly refused.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Statistics' }, 9));
    const rehydrated = await hydrateProfile();
    expect(rehydrated.conflictKeys).toEqual(['major']);

    // The person answers the CURRENT question, taking the cloud's value.
    commitMock.mockReset();
    const answered = await answerConflict(
      ['major'], 'cloud', token, { ...FULL, major: 'Statistics' },
    );

    // It closes. A stale receipt allowed into generic planning would compete
    // with this answer and the question could never be settled.
    expect(answered.status === 'saved' || answered.status === 'already-saved').toBe(true);
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Statistics' }, 9));
    const after = await hydrateProfile();
    expect(after.conflictKeys, 'settled for good').toEqual([]);
    expect(after.profile!.major, 'and the old value never comes back').toBe('Statistics');
  });

  it("a refresh applies another tab's answer instead of re-showing the question", async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    // TAB B answers and dies before hydrating or flushing. The receipt is on
    // disk; the outbox is still locked.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();
    const receiptsBefore = journalOps().filter((op) => op.mode === 'resolve').length;

    // TAB A still has the old prompt. Its refresh must APPLY the answer, not
    // describe the question again — the plain synchronous read would happily
    // synthesize the same pending candidate and the prompt would come back.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const refreshed = await refreshConflictQuestion(['major'], token);

    expect(refreshed.status, 'the question is gone').toBe('settled');
    expect(refreshed).toMatchObject({ conflicts: [] });
    expect(readProfileSyncEnvelope()!.pending?.lockedKeys ?? []).toEqual([]);
    expect(rawMirror()?.major, "and the answer is what is displayed").toBe('ECE');
    expect(journalOps().filter((op) => op.mode === 'resolve').length,
      'no duplicate receipt').toBeLessThanOrEqual(receiptsBefore);
    // The answer is KEEP MINE, and the cloud still holds the other value: the
    // repair took the last lock off a write that is still owed, so the refresh
    // finishes it. Stopping at the local repair applies the answer on this
    // device and silently never sends it.
    expect(commitMock.mock.calls.map((c) => c[0].patch),
      'the answer is carried through to the server').toEqual([{ major: 'ECE' }]);
    expect(refreshed.status === 'settled' && refreshed.flushed?.status,
      'and the flush it continued is reported, not swallowed').toBe('saved');
  });

  it('a refresh publishes only the question that is genuinely still open', async () => {
    // Two fields locked; only one is answered.
    localStorage.setItem(
      STORAGE_KEYS.PROFILE,
      JSON.stringify({ ...FULL, major: 'ECE', college: 'LAS' }),
    );
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics', college: 'Grainger' }, 8));
    const token = captureOwnerToken();
    await hydrateProfile();
    const asked = readCurrentConflicts(['major'], token);
    const envelope = readProfileSyncEnvelope()!;
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: asked[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    const refreshed = await refreshConflictQuestion(['major', 'college'], token);
    expect(refreshed.status, 'a real question is still open').toBe('current');
    expect(
      refreshed.status === 'current' ? refreshed.conflicts.map((c) => c.key) : null,
      'only the one still in dispute',
    ).toEqual(['college']);
  });

  it('a pending-only answer that goes through a NEW mutation still settles its receipt', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);

    // The ordinary public path: answer, which repairs the pending write and
    // then stages it as a new mutation.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const answered = await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'local',
      { ...FULL, major: 'ECE' },
    ));
    expect(answered.status).toBe('saved');

    // The receipt was acknowledged with that save. Rebuilding the new
    // mutation's ownership from scratch drops it — the answer lands, the
    // receipt stays outstanding, and it leaks toward the cap.
    expect(journalOps().filter((op) => op.mode === 'resolve'),
      'the receipt is settled, not left outstanding').toEqual([]);

    // A REAL reload, then the row moves again: the old answer never revives.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Statistics' }, 10));
    const later = await hydrateProfile();
    expect(later.profile!.major).toBe('Statistics');
    expect(later.conflictKeys).toEqual([]);
    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('a settled answer cannot revive: second reload, then a later remote change', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    // The answer is repaired and sent.
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    await hydrateProfile();
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    expect((await flushPendingProfileWrite(token)).status).toBe('saved');

    // Confirmed, so the receipt is settled — not left outstanding for the
    // next reader to replay as an ordinary edit.
    expect(journalOps().filter((op) => op.mode === 'resolve'),
      'the receipt was acknowledged with the save').toEqual([]);

    // A SECOND reload, and then another device moves the field again.
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Statistics' }, 10));
    const later = await hydrateProfile();

    // The old choice does not come back and does not re-open a question.
    expect(later.profile!.major).toBe('Statistics');
    expect(later.conflictKeys).toEqual([]);
    commitMock.mockReset();
    await flushPendingProfileWrite(token);
    expect(commitMock, 'and nothing is re-sent').not.toHaveBeenCalled();
  });

  it('a receipt about revision 8 does not answer a question that has moved to revision 9', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    // The answer lands durably, and the process dies before it is sent.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    // Meanwhile ANOTHER device takes the same field somewhere else entirely.
    // This browser reloads and rebases onto revision 9 — same mutation, same
    // field version, a completely different disagreement.
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Statistics' }, 9));
    const rehydrated = await hydrateProfile();
    expect(rehydrated.conflictKeys).toEqual(['major']);

    commitMock.mockReset();
    const flushed = await flushPendingProfileWrite(token);

    // Matching on mutation + version alone would accept the revision-8 answer
    // here and send 'ECE' with expectedRevision 9 — which the server applies,
    // legally, over a value nobody on this device has ever seen.
    expect(flushed.status).toBe('conflict');
    expect(commitMock, 'zero network').not.toHaveBeenCalled();
    expect(readProfileSyncEnvelope()!.pending!.lockedKeys,
      'the question stays open for someone who can see it').toEqual(['major']);
  });

  it('a receipt for a DIFFERENT field version does not unlock this question', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    const envelope = readProfileSyncEnvelope()!;

    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: envelope.pending!.mutationId,
        keyVersions: { major: question[0].keyVersion! + 99 },
      },
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    resetProfileDirtyLedger();
    commitMock.mockReset();
    const flushed = await flushPendingProfileWrite(token);
    expect(flushed.status, 'a different version is a different disagreement').toBe('conflict');
    expect(commitMock).not.toHaveBeenCalled();
  });

  it('a malformed pending target is refused by the journal outright', () => {
    const token = captureOwnerToken();
    // No mutationId.
    expect(appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'X' } }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: { mutationId: '', keyVersions: { major: 1 } },
      decisions: { major: 'local' },
    } as never, token)).toBeNull();
    // A version that is not a whole number.
    expect(appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'X' } }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: { mutationId: 'm', keyVersions: { major: 1.5 } },
      decisions: { major: 'local' },
    } as never, token)).toBeNull();
    // A target naming a key this receipt does not decide.
    expect(appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'X' } }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: { mutationId: 'm', keyVersions: { college: 1 } },
      decisions: { major: 'local' },
    } as never, token)).toBeNull();
    // Neither target form at all.
    expect(appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'X' } }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      decisions: { major: 'local' },
    } as never, token)).toBeNull();
    // And an ORDINARY edit may not carry one.
    expect(appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'X' } }],
      baseRevision: 8,
      writer: 'default',
      mode: 'set',
      resolvesPending: { mutationId: 'm', keyVersions: { major: 1 } },
    } as never, token)).toBeNull();
  });

  /** Storage that fails exactly one key, and nothing else. */
  function breakStorage(fail: (key: string) => boolean) {
    const real = window.localStorage;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => real.getItem(k),
        setItem: (k: string, v: string) => {
          if (fail(k)) throw new Error('quota');
          real.setItem(k, v);
        },
        removeItem: (k: string) => {
          if (fail(k)) throw new Error('quota');
          real.removeItem(k);
        },
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    return () => Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
  }

  /** TAB B's durable answer to `question`, appended and never delivered. */
  function answerFromAnotherTab(
    question: readonly ProfileConflict[],
    token: OwnerToken,
    choice: 'local' | 'cloud' = 'local',
  ) {
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: choice === 'local' ? 'ECE' : 'Physics' },
      }],
      baseRevision: question[0].remoteRevision,
      writer: 'default',
      mode: 'resolve',
      resolvesPending: {
        mutationId: question[0].mutationId!,
        keyVersions: { major: question[0].keyVersion! },
      },
      decisions: { major: choice },
    }, token)).toBeTruthy();
  }

  it('U-C2: a stage conflict is the OUTER canonical question, not a nested payload', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    // A journal-only answer: the winning value lives in the journal and has
    // never been staged, so this refresh owes the network a send.
    answerFromAnotherTab(question, token, 'local');

    // The row moved again underneath it: the send collides. Hold it open and
    // record a NEWER local intent while it is in flight — the send's own
    // payload cannot know about that, so a result assembled from it describes
    // a question that is already out of date.
    let release!: (v: ProfilePatchOutcome) => void;
    commitMock.mockReset();
    commitMock.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    const inFlight = refreshConflictQuestion(['major'], token);
    await vi.waitFor(() => expect(commitMock).toHaveBeenCalledTimes(1));
    expect(recordProfileIntent(
      { ...FULL, major: 'Math' } as ProfileData, ['major'], token,
      { writer: HOME_FORM_WRITER },
    ), 'a newer intent lands while the send is open').toBeTruthy();
    release(conflict({ ...FULL, major: 'Statistics' }, 9));
    const refreshed = await inFlight;

    expect(refreshed.status,
      'the refresh itself reports the disagreement it just discovered').toBe('current');
    expect(refreshed.status === 'current' ? refreshed.conflicts.map((c) => c.key) : [],
      'named at the top level, so no caller has to open a nested payload')
      .toEqual(['major']);
    expect(refreshed.status === 'current' ? refreshed.revision : -1,
      'at the revision the server just reported').toBe(9);
    expect(
      refreshed.status === 'current' ? refreshed.baseProfile?.major : null,
      'against the row the server actually holds',
    ).toBe('Statistics');
    // THE POINT: the question is re-derived from what is durable now, so it
    // knows about the intent recorded during the send. The send's own conflict
    // payload was assembled before that op existed and cannot name it.
    const shown = refreshed.status === 'current'
      ? refreshed.conflicts[0].candidates.map((c) => c.value)
      : [];
    expect(shown, 'and it describes the disagreement as it stands NOW')
      .toContain('Math');
  });

  it('U-C1: work recorded while the send was in flight is in the FINAL answer', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token, 'local');

    // Hold the send open, record a NEWER edit while it is, then let it land.
    let release!: (v: ProfilePatchOutcome) => void;
    commitMock.mockReset();
    commitMock.mockImplementation(() => new Promise((resolve) => { release = resolve; }));
    const inFlight = refreshConflictQuestion(['major'], token);
    await vi.waitFor(() => expect(commitMock).toHaveBeenCalledTimes(1));

    expect(recordProfileIntent(
      { ...FULL, major: 'Math' } as ProfileData, ['major'], token,
      { writer: HOME_FORM_WRITER },
    ), 'the newer edit really was recorded').toBeTruthy();

    release(saved({ ...FULL, major: 'ECE' }, 9));
    const refreshed = await inFlight;

    expect(commitMock, 'exactly one network call — no recursion').toHaveBeenCalledTimes(1);
    expect(refreshed.status).not.toBe('device-failed');
    const st = refreshed as Extract<typeof refreshed, { pendingKeys: string[] }>;
    expect(st.baseProfile?.major, 'the base is what the server confirmed').toBe('ECE');
    expect(st.revision, 'at its revision').toBe(9);
    expect(st.profile?.major, 'but the screen shows the newer edit').toBe('Math');
    expect(st.pendingKeys, 'which is still owed, because it was never sent')
      .toContain('major');
  });

  it('U-C3: a postflight read failure fails closed, never "settled"', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token, 'local');

    // The device breaks AFTER the cloud confirm — the postflight re-read is
    // the thing that cannot be done. Reporting "settled" here would take the
    // controls off a question this browser can no longer account for.
    let restore: (() => void) | null = null;
    commitMock.mockReset();
    commitMock.mockImplementation(async () => {
      restore = breakStorage(() => true);
      return saved({ ...FULL, major: 'ECE' }, 9);
    });

    let refreshed;
    try {
      refreshed = await refreshConflictQuestion(['major'], token);
    } finally {
      (restore as (() => void) | null)?.();
    }

    expect(refreshed.status, 'the device says so out loud').toBe('device-failed');
  });

  it('U-C3b: an unreadable journal in the POSTFLIGHT is device-failed, not settled', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token, 'local');

    // The lock is fine; what this browser cannot do is read its own journal
    // back after the send. Answering "settled" from the pre-send read would
    // retire a question against state nobody has verified.
    // Corrupt it only once the send has finished its OWN local work — the
    // receipt write is the last thing it does — so the failure belongs to the
    // postflight re-read and to nothing else.
    const real = window.localStorage;
    let sent = false;
    let corrupted = false;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => real.getItem(k),
        setItem: (k: string, v: string) => {
          real.setItem(k, v);
          if (sent && !corrupted && k.startsWith(STORAGE_KEYS.PROFILE_JOURNAL_PREFIX)) {
            corrupted = true;
            real.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_corrupt`, '{not json');
          }
        },
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    commitMock.mockReset();
    commitMock.mockImplementation(async () => {
      sent = true;
      return saved({ ...FULL, major: 'ECE' }, 9);
    });

    let refreshed;
    try {
      refreshed = await refreshConflictQuestion(['major'], token);
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }
    expect(corrupted, 'the journal really was corrupted after the send').toBe(true);

    expect(refreshed.status, 'the device says so out loud').toBe('device-failed');
    expect(refreshed).toMatchObject({ phase: 'journal', retryable: true });
  });

  it('U-C6: an abandoned send is never swallowed back into the preflight snapshot', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token, 'local');

    // The owner moves while the send is open: what comes back belongs to
    // nobody, and the pre-send snapshot is not a substitute for it.
    commitMock.mockReset();
    commitMock.mockImplementation(async () => {
      advanceOwnerEpoch('unit-c-u2');
      await syncLocalIdentityOwner('unit-c-u2');
      return saved({ ...FULL, major: 'ECE' }, 9);
    });

    const refreshed = await refreshConflictQuestion(['major'], token);

    expect(refreshed.status, "a superseded owner gets no answer at all").toBe('abandoned');
  });

  it('a refresh that cannot read the journal keeps the question and blames the DEVICE', async () => {
    const token = captureOwnerToken();
    await pendingOnlyConflict(token);
    const envelopeBefore = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    const mirrorBefore = localStorage.getItem(STORAGE_KEYS.PROFILE);
    // Another tab's operation, unreadable by this build.
    localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_corrupt`, '{not json');

    commitMock.mockReset();
    const refreshed = await refreshConflictQuestion(['major'], token);

    expect(refreshed.status, 'not "settled" — this browser simply could not look')
      .toBe('device-failed');
    expect(refreshed).toMatchObject({ phase: 'journal', retryable: true });
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC), 'nothing written')
      .toBe(envelopeBefore);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE)).toBe(mirrorBefore);
    expect(commitMock, 'and nothing sent past the failing boundary').not.toHaveBeenCalled();
  });

  it('a refresh whose envelope write fails keeps the answer and names the phase', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token);
    const mirrorBefore = localStorage.getItem(STORAGE_KEYS.PROFILE);

    commitMock.mockReset();
    const restore = breakStorage((k) => k === STORAGE_KEYS.PROFILE_SYNC);
    let refreshed;
    try {
      refreshed = await refreshConflictQuestion(['major'], token);
    } finally {
      restore();
    }

    expect(refreshed.status).toBe('device-failed');
    expect(refreshed).toMatchObject({ phase: 'envelope', retryable: true });
    expect(journalOps().some((op) => op.mode === 'resolve'),
      'the proof survives — it is the only record the answer was ever given').toBe(true);
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE),
      'and the mirror is not moved by a repair that did not land').toBe(mirrorBefore);
    expect(commitMock, 'zero network').not.toHaveBeenCalled();
  });

  it('a refresh whose MIRROR write fails is finished by the next one, envelope already repaired', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    // USE CLOUD: the answer is the row's own value, so applying it has to
    // change what this device displays.
    answerFromAnotherTab(question, token, 'cloud');

    commitMock.mockReset();
    const restore = breakStorage((k) => k === STORAGE_KEYS.PROFILE);
    let first;
    try {
      first = await refreshConflictQuestion(['major'], token);
    } finally {
      restore();
    }

    expect(first.status).toBe('device-failed');
    expect(first).toMatchObject({ phase: 'mirror', retryable: true });
    // The envelope IS repaired: half the work landed.
    expect(readProfileSyncEnvelope()!.pending?.lockedKeys ?? [],
      'the outbox is already correct').toEqual([]);
    expect(rawMirror()?.major, 'and the mirror is still showing the disputed value')
      .toBe('ECE');

    // The retry finds NOTHING left to repair in the outbox. Skipping the
    // mirror because "the envelope did not change on this pass" is what
    // leaves every other screen wrong for good.
    const second = await refreshConflictQuestion(['major'], token);
    expect(second.status, 'the question really is gone now').toBe('settled');
    expect(rawMirror()?.major, 'and the mirror agrees with the answer').toBe('Physics');
    expect(commitMock, 'the chosen value IS the row: nothing to send')
      .not.toHaveBeenCalled();
  });

  it('a refresh for an owner who has been replaced applies nothing at all', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token);

    // A different account owns the browser now.
    await seedOwner('sync-u2');
    const envelopeBefore = localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC);
    commitMock.mockReset();
    const refreshed = await refreshConflictQuestion(['major'], token);

    expect(refreshed.status, "the old identity's news is nobody's").toBe('abandoned');
    expect(localStorage.getItem(STORAGE_KEYS.PROFILE_SYNC), 'zero storage mutation')
      .toBe(envelopeBefore);
    expect(commitMock, 'zero network').not.toHaveBeenCalled();
  });

  it('a refresh reports a disagreement that lives only in the journal', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 8));
    const token = captureOwnerToken();
    await hydrateProfile();

    // Two tabs, two different values for the same field, neither sent. The
    // outbox never locks this: it is the journal that says they disagree.
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    startDocumentForTests('other');
    recordProfileIntent({ ...FULL, major: 'Statistics' }, ['major'], token);

    commitMock.mockReset();
    const refreshed = await refreshConflictQuestion(['major'], token);

    expect(refreshed.status, 'a live question, not a settled one').toBe('current');
    const conflicts = refreshed.status === 'current' ? refreshed.conflicts : [];
    expect(conflicts.map((c) => c.key)).toEqual(['major']);
    expect(
      conflicts[0].candidates.map((c) => c.value).sort(),
      'both tabs, with their own operations behind them',
    ).toEqual(['ECE', 'Statistics']);
    expect(conflicts[0].candidates.every((c) => c.opIds.length > 0)).toBe(true);
    expect(commitMock, 'and nothing is sent while they disagree').not.toHaveBeenCalled();
  });

  it('a refresh carries the row, the accepted base and its revision from ONE read', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token, 'cloud');

    commitMock.mockReset();
    const refreshed = await refreshConflictQuestion(['major'], token);

    expect(refreshed.status).toBe('settled');
    if (refreshed.status !== 'settled') throw new Error('unreachable');
    expect(refreshed.profile!.major, 'what the screen should show').toBe('Physics');
    expect(refreshed.baseProfile!.major, 'the accepted baseline').toBe('Physics');
    expect(refreshed.revision, 'and the revision that baseline IS').toBe(8);
    expect(refreshed.pendingKeys, 'nothing is owed any more').toEqual([]);
    expect(commitMock, 'the chosen value IS the row: nothing to send')
      .not.toHaveBeenCalled();
  });

  it('an acknowledgement that half-landed is RESUMED by the next refresh, not lost', async () => {
    const token = captureOwnerToken();
    const question = await pendingOnlyConflict(token);
    answerFromAnotherTab(question, token, 'cloud');

    // The repair lands, the ack is recorded, and removing the operation's own
    // key fails. Readers already skip acked ids, so nothing can ever
    // rediscover this as finished work — only the ack record itself knows.
    commitMock.mockReset();
    const restore = breakStorage((k) => k.startsWith(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_`));
    let first;
    try {
      first = await refreshConflictQuestion(['major'], token);
    } finally {
      restore();
    }

    expect(first.status, 'the repair landed; the housekeeping did not').toBe('device-failed');
    expect(first).toMatchObject({ phase: 'settle', retryable: true });
    expect(readProfileSyncEnvelope()!.pending?.lockedKeys ?? [],
      'the answer itself is applied').toEqual([]);
    expect(commitMock, 'and no duplicate request came out of it').not.toHaveBeenCalled();

    // Storage recovers. The retry has NOTHING new to acknowledge — it has to
    // resume the ack that is already on disk.
    const second = await refreshConflictQuestion(['major'], token);
    expect(second.status, 'and now it is finished').toBe('settled');
    expect(localStorage.getItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}ack`),
      'the ack record itself is gone too').toBeNull();
    expect(
      Object.keys(localStorage).filter(
        (k) => k.startsWith(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_`),
      ),
      'and so is every operation it named',
    ).toEqual([]);

    // A real reload never re-asks and never revives it.
    startDocumentForTests('reload');
    resetProfileDirtyLedger();
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    const after = await hydrateProfile();
    expect(after.conflictKeys).toEqual([]);
    expect(after.profile!.major).toBe('Physics');
  });

  it("a journal-only disagreement answered by another tab is DELIVERED, not silently settled", async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 8));
    const token = captureOwnerToken();
    await hydrateProfile();

    // Two tabs, two values, neither sent. Nothing locks in the outbox — the
    // disagreement lives entirely in the journal.
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    const mine = journalOps().filter((op) => op.fields.some((f) => f.key === 'major'));
    startDocumentForTests('other');
    recordProfileIntent({ ...FULL, major: 'Statistics' }, ['major'], token);
    const theirs = journalOps()
      .filter((op) => op.fields.some((f) => f.key === 'major'))
      .filter((op) => !mine.some((m) => m.opId === op.opId));
    expect(theirs).toHaveLength(1);

    // Another tab answers it: keep the ECE side.
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'CS' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolves: theirs.map((op) => op.opId),
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const refreshed = await refreshConflictQuestion(['major'], token);

    // Settling to the CONFIRMED row here would report the disagreement gone
    // while the value that won it has never left this browser.
    expect(refreshed.status).toBe('settled');
    if (refreshed.status !== 'settled') throw new Error('unreachable');
    expect(refreshed.profile!.major, 'the answer is what the screen gets').toBe('ECE');
    expect(commitMock.mock.calls.map((c) => c[0].patch),
      'and it is actually delivered').toEqual([{ major: 'ECE' }]);
    expect(refreshed.flushed?.status, 'reported through the same result').toBe('saved');
    expect(rawMirror()?.major, 'with every other screen agreeing').toBe('ECE');
  });

  it('a journal-only answer whose local staging fails is retryable, and its proof survives', async () => {
    loadProfileMock.mockResolvedValue(cloud(FULL, 8));
    const token = captureOwnerToken();
    await hydrateProfile();
    recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token);
    const mine = journalOps().filter((op) => op.fields.some((f) => f.key === 'major'));
    startDocumentForTests('other');
    recordProfileIntent({ ...FULL, major: 'Statistics' }, ['major'], token);
    const theirs = journalOps()
      .filter((op) => op.fields.some((f) => f.key === 'major'))
      .filter((op) => !mine.some((m) => m.opId === op.opId));
    expect(appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'CS' },
        desired: { present: true, value: 'ECE' },
      }],
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      resolves: theirs.map((op) => op.opId),
      decisions: { major: 'local' },
    }, token)).toBeTruthy();

    commitMock.mockReset();
    const restore = breakStorage((k) => k === STORAGE_KEYS.PROFILE_SYNC);
    let refreshed;
    try {
      refreshed = await refreshConflictQuestion(['major'], token);
    } finally {
      restore();
    }

    // Nothing durable holds the answer yet, so 'settled' would take the
    // controls off a decision that can still be lost.
    expect(refreshed.status).toBe('device-failed');
    expect(refreshed).toMatchObject({ phase: 'stage', retryable: true });
    expect(commitMock, 'zero cloud write').not.toHaveBeenCalled();
    // The proof is still on disk: settling its closure before the value was
    // staged would make the choice unrecoverable.
    expect(journalOps().some((op) => op.mode === 'resolve'),
      'the receipt survives the failure').toBe(true);
    expect(journalOps().some((op) => op.opId === mine[0].opId),
      'and so does the edit it chose').toBe(true);

    // The retry sends the chosen value exactly once, and only then retires it.
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    const second = await refreshConflictQuestion(['major'], token);
    expect(second.status).toBe('settled');
    if (second.status !== 'settled') throw new Error('unreachable');
    expect(commitMock.mock.calls.map((c) => c[0].patch)).toEqual([{ major: 'ECE' }]);
    expect(second.revision, 'the revision the server issued').toBe(9);
    expect(second.profile!.major).toBe('ECE');
    expect(second.pendingKeys, 'and nothing is owed any more').toEqual([]);
    expect(journalOps().filter((op) => op.mode === 'resolve'),
      'only now is the proof retired').toEqual([]);
  });

  it('an authoritative EMPTY row clears the legacy mirror, and a clear that fails is reported', async () => {
    // The row is gone from the cloud and nothing is pending: the working copy
    // this refresh reports is genuine absence. A legacy mirror left behind is
    // what every other screen keeps rendering.
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ ...FULL, major: 'ECE' }));
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 8));
    const token = captureOwnerToken();
    await hydrateProfile();
    const question = readCurrentConflicts(['major'], token);
    expect((await resolveProfileConflict(answerOn(
      viewOf({ ...FULL, major: 'ECE' }, 8, token),
      question,
      'cloud',
      { ...FULL, major: 'ECE' },
    ))).status).toBe('already-saved');
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1, confirmed: null, pending: null, tombstone: null,
    }));

    commitMock.mockReset();
    const restore = breakStorage((k) => k === STORAGE_KEYS.PROFILE);
    let failed;
    try {
      failed = await refreshConflictQuestion(['major'], token);
    } finally {
      restore();
    }
    expect(failed.status, 'a mirror this browser could not clear is not a settled question')
      .toBe('device-failed');
    expect(failed).toMatchObject({ phase: 'mirror', retryable: true });
    expect(rawMirror(), 'and the stale copy is still there to be cleared').not.toBeNull();

    const second = await refreshConflictQuestion(['major'], token);
    expect(second.status).toBe('settled');
    expect(rawMirror(), 'the legacy copy is gone').toBeNull();
    expect(commitMock, 'with no request anywhere in it').not.toHaveBeenCalled();
  });

  it('a question is labelled with the revision it READ, not one that lands mid-build', async () => {
    const token = captureOwnerToken();
    await pendingOnlyConflict(token);

    // Another tab confirms revision 9 the instant after the question's first
    // envelope read. A second read taken while the payload is being built
    // would staple revision 9 onto the revision-8 row that is actually being
    // described — a pair that never existed, and the exact pair a receipt
    // would then record as the thing the person was shown.
    const real = window.localStorage;
    const later = JSON.stringify({
      ...JSON.parse(real.getItem(STORAGE_KEYS.PROFILE_SYNC)!),
      confirmed: { revision: 9, profile: { ...FULL, major: 'Statistics' } },
    });
    let envelopeReads = 0;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => {
          if (k !== STORAGE_KEYS.PROFILE_SYNC) return real.getItem(k);
          envelopeReads += 1;
          return envelopeReads === 1 ? real.getItem(k) : later;
        },
        setItem: (k: string, v: string) => real.setItem(k, v),
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    let question;
    try {
      question = readCurrentConflicts(['major'], token);
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }

    expect(question[0].remote, 'the row that was actually read').toBe('Physics');
    expect(question[0].remoteRevision, 'and its own revision, not a later one').toBe(8);
    expect(envelopeReads, 'ONE envelope read builds the whole question').toBe(1);
  });
});

describe('a slow cloud row that arrives behind a newer local one', () => {
  it('revision 8 landing after revision 9 leaves hydration, envelope and mirror all at 9', async () => {
    // This device already knows revision 9 when the read is ISSUED, so the
    // request-start fence is 9 too. Only comparing against the ANSWER's own
    // revision catches this — a fence comparison sees 9 > 9 and lets the
    // older row straight through.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Nine' }, 9));
    const token = captureOwnerToken();
    await hydrateProfile();
    expect(readProfileSyncEnvelope()!.confirmed!.revision).toBe(9);

    let release: ((v: LoadedProfile) => void) | undefined;
    loadProfileMock.mockImplementationOnce(() => new Promise<LoadedProfile>((resolve) => {
      release = resolve;
    }));
    const inFlight = hydrateProfile();
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();

    // A slow replica answers with revision 8.
    release!({ source: 'cloud', profile: { ...FULL, major: 'Eight' }, revision: 8, token });
    const hydration = await inFlight;

    // ALL THREE agree, and all three are the newer row. A returned revision 8
    // beside an envelope at 9, or a mirror rewritten to 8, is a screen showing
    // one moment while the outbox believes another.
    expect(hydration.revision).toBe(9);
    expect(hydration.baseProfile!.major).toBe('Nine');
    expect(hydration.profile!.major).toBe('Nine');
    expect(readProfileSyncEnvelope()!.confirmed!.revision).toBe(9);
    expect(readProfileSyncEnvelope()!.confirmed!.profile.major).toBe('Nine');
    expect(rawMirror()?.major).toBe('Nine');
  });
});

describe('the ledger cache replays receipts through live ancestry', () => {
  it('A <- live B <- C survives a cache rebuild and the NEXT REQUEST uses A\'s landed revision', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 1));
    const token = captureOwnerToken();
    await hydrateProfile();

    const server = casServer({ ...FULL, major: 'CS' }, 1);
    let release: (() => void) | undefined;
    commitMock.mockReset();
    commitMock.mockImplementationOnce((intent) => new Promise<ProfilePatchOutcome>((resolve) => {
      release = () => resolve(server.handle(intent) as ProfilePatchOutcome);
    }));
    expect(recordProfileIntent({ ...FULL, major: 'ECE' }, ['major'], token)).toBe(true);
    const inFlight = stageProfilePatch({ ...FULL, major: 'ECE' }, ['major'], token);
    for (let i = 0; i < 50 && !release; i += 1) await Promise.resolve();
    expect(recordProfileIntent({ ...FULL, major: 'Physics' }, ['major'], token)).toBe(true);
    const b = journalOps().find((op) => (op.supersedes ?? []).length > 0)!;
    // C names ONLY B, so the link to A exists solely through a live operation.
    appendJournalOp({
      fields: [{
        key: 'major',
        base: { present: true, value: 'Physics' },
        desired: { present: true, value: 'Math' },
      }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
      supersedes: [b.opId],
      lineage: b.lineage,
    }, token);
    release!();
    await inFlight;

    // Reload: every in-memory cache is gone and must be rebuilt from storage.
    resetProfileDirtyLedger();
    commitMock.mockReset();
    commitMock.mockImplementation((intent) => Promise.resolve(server.handle(intent) as ProfilePatchOutcome));
    const next = await flushPendingProfileWrite(token);

    // The REAL request, not a helper's opinion of it.
    expect(next.status).toBe('saved');
    expect(server.seen.at(-1)!.expected, 'A\'s landed revision, reached through live B').toBe(2);
    expect(server.row.major).toBe('Math');
  });
});

describe('a fenced row has no view at all', () => {
  it('a deleted tombstone with a quarantined pending entry still yields nothing to render', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    const envelope = readProfileSyncEnvelope()!;

    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: null,
      // Quarantined, not erased — this is exactly what the deletion path
      // leaves behind when the mirror removal succeeded.
      pending: envelope.pending ?? {
        mutationId: 'm1',
        baseRevision: 7,
        baseProfile: { ...FULL, major: 'CS' },
        desiredProfile: { ...FULL, major: 'Physics' },
        dirtyKeys: ['major'],
        lockedKeys: [],
        journalOpIds: [],
        journalPlan: {},
        keyVersions: {},
        skillAdditions: [],
        skillsReplaced: false,
        skillOps: [],
        additiveKeys: [],
        conflictRemote: null,
        legacy: false,
        deferredCreate: false,
      },
      tombstone: { reason: 'deleted', rawQuarantined: true },
    }));

    // workingCopy(null, pending, null) would happily rebuild a profile out of
    // that pending entry — and Results would render it and match against it.
    expect(readProfileView(token)).toBeNull();
  });

  it('a merged-away account is fenced the same way', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: { revision: 7, profile: { ...FULL, major: 'CS' } },
      pending: null,
      tombstone: { reason: 'merged', rawQuarantined: true },
    }));
    expect(readProfileView(token)).toBeNull();
  });
});

describe('a hydration reports ONE pair, from ONE read', () => {
  it('an unmergeable load reports the envelope\'s own base and revision — never the network\'s revision', async () => {
    // Get a real confirmed row into the envelope first.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    await hydrateProfile();
    expect(readProfileSyncEnvelope()!.confirmed!.revision).toBe(7);

    // Now the lock is unavailable, so this load cannot be merged in. The
    // network says revision 30; the envelope still holds revision 7 and the
    // 'CS' row. Reporting 30 beside that row would tell the caller its
    // baseline is 23 revisions newer than it is — and a CAS built from the
    // pair would be aimed at a row this device has never seen.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'Physics' }, 30));
    const locks = navigator.locks;
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    let hydration;
    try {
      hydration = await hydrateProfile();
    } finally {
      Object.defineProperty(navigator, 'locks', { configurable: true, value: locks });
    }
    expect(hydration.quarantineFailed, 'nothing was merged').toBe(true);
    expect(hydration.revision).toBe(7);
    expect(hydration.baseProfile!.major).toBe('CS');
    expect(hydration.revision, 'never the revision of the row it could not merge').not.toBe(30);
  });

  it('that same path parses the envelope ONCE', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    await hydrateProfile();

    const locks = navigator.locks;
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    // jsdom's Storage is a proxy that swallows a spy on its methods — the
    // accessor itself has to be replaced to see the calls.
    const real = window.localStorage;
    let envelopeReads = 0;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => {
          if (k === STORAGE_KEYS.PROFILE_SYNC) envelopeReads += 1;
          return real.getItem(k);
        },
        setItem: (k: string, v: string) => real.setItem(k, v),
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    try {
      await hydrateProfile();
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
      Object.defineProperty(navigator, 'locks', { configurable: true, value: locks });
    }
    // Exactly two: the pre-flight `observedBefore` read taken BEFORE the
    // network call, and the one snapshot every returned field comes out of.
    // The old shape read it five more times — once per field — which is five
    // chances for another tab to land in between and for the fields to end up
    // describing different moments.
    expect(envelopeReads).toBe(2);
  });

  it('a local-only load reports an explicitly unknown baseline, not an old row at revision 0', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    await hydrateProfile();

    loadProfileMock.mockResolvedValue({
      source: 'local-only' as const,
      profile: { ...FULL, major: 'CS' },
      revision: 0,
      token: captureOwnerToken(),
    });
    const hydration = await hydrateProfile();
    expect(hydration.revision).toBe(0);
    // The pair has to agree: revision 0 means "no known row", so there is no
    // baseline to hand out either.
    expect(hydration.baseProfile).toBeNull();
    // The working copy is still shown — the user keeps seeing their profile.
    expect(hydration.profile!.major).toBe('CS');
  });

  it('readProfileView never mixes the raw mirror into an envelope-backed view', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();

    // A raw mirror that DISAGREES with the envelope — exactly what a partial
    // write or an older build leaves behind.
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ ...FULL, major: 'Mirror' }));

    // The whole accessor, not vi.spyOn: jsdom's Storage is a proxy that
    // swallows a spy on its methods, so a spy-based count reads zero for
    // BOTH the fixed and the broken version.
    const real = window.localStorage;
    let mirrorReads = 0;
    let envelopeReads = 0;
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => {
          if (k === STORAGE_KEYS.PROFILE) mirrorReads += 1;
          if (k === STORAGE_KEYS.PROFILE_SYNC) envelopeReads += 1;
          return real.getItem(k);
        },
        setItem: (k: string, v: string) => real.setItem(k, v),
        removeItem: (k: string) => real.removeItem(k),
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    let view;
    try {
      view = readProfileView(token)!;
    } finally {
      Object.defineProperty(window, 'localStorage', { configurable: true, value: real });
    }

    expect(envelopeReads, 'one parse decides everything').toBe(1);
    expect(mirrorReads, 'the mirror is a second key at a second moment').toBe(0);
    expect(view.renderedProfile.major).toBe('CS');
    expect(view.revision).toBe(7);
  });
});

describe('a view snapshot is a deep, frozen copy', () => {
  it('severs every alias to the caller, freezes recursively, and leaves the caller\'s own objects alone', () => {
    const owner = captureOwnerToken();
    const epochAtCapture = owner.epoch;
    const base = {
      ...FULL,
      skills: [{ name: 'Rust', level: 'expert' as const }],
    } as ProfileData;
    const rendered = {
      ...FULL,
      skills: [{ name: 'Rust', level: 'expert' as const }],
    } as ProfileData;
    const view = makeProfileViewSnapshot({
      baseProfile: base,
      renderedProfile: rendered,
      revision: 5,
      token: owner,
      identityGeneration: owner.epoch,
      source: 'hydration',
    });

    // The caller keeps mutating its own objects afterwards — as a live form
    // does. None of it may reach the baseline it is judged against.
    base.skills[0].level = 'beginner';
    base.skills.push({ name: 'Go', level: 'beginner' });
    rendered.skills[0].name = 'tampered';
    owner.epoch = 999;

    expect(view.baseProfile!.skills).toEqual([{ name: 'Rust', level: 'expert' }]);
    expect(view.renderedProfile.skills[0].name).toBe('Rust');
    expect(view.token.epoch).toBe(epochAtCapture);

    // ...and the caller's objects are still THEIRS: taking a snapshot must
    // not freeze something the caller still owns and still writes to.
    expect(Object.isFrozen(base)).toBe(false);
    expect(Object.isFrozen(owner)).toBe(false);

    // Frozen all the way down, not just at the top.
    expect(Object.isFrozen(view)).toBe(true);
    expect(Object.isFrozen(view.baseProfile)).toBe(true);
    expect(Object.isFrozen(view.baseProfile!.skills)).toBe(true);
    expect(Object.isFrozen(view.baseProfile!.skills[0])).toBe(true);
    expect(Object.isFrozen(view.renderedProfile.skills[0])).toBe(true);
    expect(Object.isFrozen(view.token)).toBe(true);
    expect(() => {
      (view.baseProfile!.skills[0] as { level: string }).level = 'beginner';
    }).toThrow();
    expect(() => {
      (view.baseProfile!.skills as { push: (x: unknown) => void }).push({ name: 'X' });
    }).toThrow();
  });
});

describe('the baseline is what the ROW holds, not what the screen shows', () => {
  it('choosing the value the UI was already defaulting to is a real change and IS sent', async () => {
    // The row has no home_school. The form shows UIUC because UIUC is the
    // matcher's default, and the person confirms exactly that. If the
    // rendered document were used as the baseline, base and desired would be
    // identical, the operation would look like a no-op, and the confirmation
    // they just made would never reach the row.
    // A row with NO home_school key at all — not one set to undefined, which
    // is a present key and would compare differently.
    const exactBase = { ...FULL } as Record<string, unknown>;
    delete exactBase.home_school;
    loadProfileMock.mockResolvedValue(cloud(exactBase as unknown as ProfileData, 5));
    const token = captureOwnerToken();
    await hydrateProfile();

    const view = makeProfileViewSnapshot({
      baseProfile: exactBase as unknown as ProfileData,
      renderedProfile: { ...FULL, home_school: 'uiuc' },
      revision: 5,
      token,
      identityGeneration: token.epoch,
      source: 'hydration',
    });
    expect(
      Object.hasOwn(view.baseProfile as object, 'home_school'),
      'the baseline preserves the ABSENCE of the key, not an undefined value',
    ).toBe(false);
    expect(Object.hasOwn(view.renderedProfile as object, 'home_school')).toBe(true);

    commitMock.mockReset();
    // The send fails, so the operation stays in the journal and can be read
    // back. A successful send settles and removes it — and what it RECORDED
    // is the half that matters here.
    commitMock.mockResolvedValueOnce({ status: 'transport-error', message: 'offline' });
    const action = await commitProfileAction({
      keys: ['home_school'],
      view,
      desiredAfter: { ...view.renderedProfile, home_school: 'uiuc' } as ProfileData,
      writer: 'school-gate',
    });

    expect(action.durable).toBe(true);
    expect(commitMock).toHaveBeenCalledTimes(1);
    expect(commitMock.mock.calls[0][0].patch).toEqual({ home_school: 'uiuc' });

    // The DURABLE record is where this actually bites: the journal operation
    // has to say the field was absent and is now 'uiuc'. Recording the
    // rendered default as the base makes base === value, which is an
    // operation that claims nothing changed — it survives a lost response as
    // "already done" and answers a conflict with the wrong side.
    const op = journalOps().find((o) => o.fields.some((f) => f.key === 'home_school'));
    expect(op, 'the intent was recorded at all').toBeTruthy();
    const field = op!.fields.find((f) => f.key === 'home_school')!;
    expect(field.desired).toEqual({ present: true, value: 'uiuc' });
    // present:false, not { present: true, value: 'uiuc' } — the row held
    // NOTHING here, and an operation whose base equals its desired value is
    // one that claims nothing changed.
    expect(field.base, 'the base is what the ROW held: nothing').toEqual({ present: false });
  });
});

describe('an action is recorded against what the person SAW, not the newest shared state', () => {
  it('a stale tab editing a field another tab has moved conflicts instead of overwriting', async () => {
    // Tab A rendered revision 7 with major 'CS'. Tab B then saved 'Physics'
    // at revision 8, and A has not heard about it. A now types 'ECE'.
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();
    // The view A accepted, taken BEFORE B's write lands — the one object the
    // action will carry.
    const accepted = readProfileView(token)!;
    expect(accepted.revision).toBe(7);
    expect(accepted.baseProfile!.major).toBe('CS');

    // Tab B's newer row arrives in the shared envelope.
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: { revision: 8, profile: { ...FULL, major: 'Physics' } },
      pending: null,
      tombstone: null,
    }));

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(conflict({ ...FULL, major: 'Physics' }, 8));
    const action = await commitProfileAction({
      keys: ['major'],
      view: accepted,
      desiredAfter: { ...accepted.renderedProfile, major: 'ECE' } as ProfileData,
      writer: 'home-form',
    });

    expect(action.durable).toBe(true);
    // The operation's BASE is what A saw — 'CS' at revision 7 — not the
    // 'Physics' the envelope has since acquired. Recording the newer value as
    // the base is what turns a genuine disagreement into a silent overwrite.
    const op = journalOps().find((o) => o.fields.some((f) => f.key === 'major'))!;
    expect(op, 'the edit was recorded').toBeDefined();
    expect(op.fields.find((f) => f.key === 'major')!.base)
      .toEqual({ present: true, value: 'CS' });
    expect(op.baseRevision).toBe(7);

    // …so the send is refused rather than clobbering tab B.
    expect(action.result?.status).toBe('conflict');
    expect(readProfileSyncEnvelope()?.confirmed?.profile.major, "tab B's value stands")
      .toBe('Physics');
  });
});


describe('the rendered baseline is one pair from one read', () => {
  it('another tab landing between two reads cannot disguise old values as newer', async () => {
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: 'CS' }, 7));
    const token = captureOwnerToken();
    await hydrateProfile();

    // The interleaving: the raw mirror still shows what this tab rendered
    // while the envelope has already moved to the other tab's revision. A
    // caller that read them separately would pair 'CS' with revision 8.
    localStorage.setItem(STORAGE_KEYS.PROFILE, JSON.stringify({ ...FULL, major: 'CS' }));
    localStorage.setItem(STORAGE_KEYS.PROFILE_SYNC, JSON.stringify({
      v: 1,
      confirmed: { revision: 8, profile: { ...FULL, major: 'Physics' } },
      pending: null,
      tombstone: null,
    }));

    const baseline = readProfileView(token)!;
    expect(baseline, 'there is a baseline').toBeTruthy();
    // Whatever it is, the value and the revision must belong to each other.
    expect(baseline.baseProfile!.major).toBe('Physics');
    expect(baseline.revision).toBe(8);
    expect(baseline.baseProfile!.major, 'never the mirror value with the new revision')
      .not.toBe('CS');

    // And an action built from it is recorded against that same pair.
    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE' }, 9));
    await commitProfileAction({
      keys: ['major'],
      view: baseline,
      desiredAfter: { ...baseline.renderedProfile, major: 'ECE' } as ProfileData,
      writer: 'results',
    });
    expect(commitMock.mock.calls[0][0].expectedRevision).toBe(8);
  });
});

describe('hydrateProfile: a failure after the read carries the identity that read', () => {
  beforeEach(async () => {
    advanceOwnerEpoch(null);
    advanceOwnerEpoch(UID);
    await syncLocalIdentityOwner(UID);
  });

  it('HS1: an already-scoped failure is passed through exactly as it was', async () => {
    const scoped = new OwnerScopedLoadError(captureOwnerToken(), new Error('select failed'));
    loadProfileMock.mockRejectedValue(scoped);

    const err = await caught(hydrateProfile());

    expect(err, 'the very same failure, unrepackaged').toBe(scoped);
    expect(scopedCapability(err).ownerToken, 'still naming the identity that read')
      .toEqual(scoped.ownerToken);
  });

  it('HS2: a reconcile this browser could not perform is scoped to the same identity', async () => {
    const token = captureOwnerToken();
    loadProfileMock.mockResolvedValue({
      source: 'cloud', profile: { ...FULL }, revision: 3, token,
    });
    // The shared lock is what every post-read reconcile runs under; a browser
    // that cannot take it fails AFTER the identity has been established.
    const had = Object.getOwnPropertyDescriptor(navigator, 'locks');
    Object.defineProperty(navigator, 'locks', {
      configurable: true,
      value: { request: () => { throw new Error('lock manager unavailable'); } },
    });
    try {
      const err = await caught(hydrateProfile());

      expect(err, 'the reconcile really failed').toBeTruthy();
      expect(scopedCapability(err).ownerToken,
        'naming the identity the read resolved').toEqual(token);
    } finally {
      if (had) Object.defineProperty(navigator, 'locks', had);
      else delete (navigator as { locks?: unknown }).locks;
    }
  });

  it('HS4: a takeover in the gap after the read is NOT this identity\'s failure', async () => {
    loadProfileMock.mockImplementation(async () => {
      const token = captureOwnerToken();
      const loaded = {
        source: 'cloud' as const, profile: { ...FULL }, revision: 3, token,
      };
      // Somebody else takes the browser over between the read returning and
      // the owner check that follows it.
      advanceOwnerEpoch('sync-u2');
      await syncLocalIdentityOwner('sync-u2');
      return loaded;
    });

    const err = await caught(hydrateProfile());

    expect((err as Error)?.name, 'this read is abandoned, not scoped')
      .toBe('OwnerNotReadyError');
    expect(claimedOwnerToken(err),
      'and it claims nobody — a blanket wrapper would tag it').toBeUndefined();
  });

  it('HS5: the SAME owner with unconfirmed local data is still scoped to them', async () => {
    const token = captureOwnerToken();
    loadProfileMock.mockImplementation(async () => {
      // uid and epoch stay exactly as they were; what goes is this browser's
      // proof that its local data belongs to them.
      localStorage.removeItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER);
      return { source: 'cloud' as const, profile: { ...FULL }, revision: 3, token };
    });

    const err = await caught(hydrateProfile());

    expect(isTokenOwnerStillCurrent(token),
      'they are still the owner of this browser').toBe(true);
    expect(isOwnerTokenValid(token, token.uid),
      'but their local data is no longer confirmed for them').toBe(false);
    expect(scopedCapability(err).ownerToken,
      'their own unusable browser is still their failure, named as theirs')
      .toEqual(token);
  });

  it('HS3: a lock that REJECTS after the read is scoped to the same identity', async () => {
    const token = captureOwnerToken();
    loadProfileMock.mockResolvedValue({
      source: 'cloud', profile: { ...FULL }, revision: 3, token,
    });
    // The asynchronous shape of the same post-read failure: the lock is
    // granted-then-lost rather than refused outright.
    const had = Object.getOwnPropertyDescriptor(navigator, 'locks');
    Object.defineProperty(navigator, 'locks', {
      configurable: true,
      value: { request: () => Promise.reject(new Error('lock lost')) },
    });
    try {
      const err = await caught(hydrateProfile());

      expect(err, 'the reconcile really failed').toBeTruthy();
      expect(scopedCapability(err).ownerToken,
        'naming the identity the read resolved').toEqual(token);
    } finally {
      if (had) Object.defineProperty(navigator, 'locks', had);
      else delete (navigator as { locks?: unknown }).locks;
    }
  });
});

describe('O6: one answer, one authority — the prompt and the value cannot be mixed', () => {
  /** A real, published `major` question for whoever owns the browser now. */
  async function questionFor(mine: string, theirs: string) {
    // Through the authority: this device's mirror belongs to whoever owns the
    // browser right now, and after an identity switch that is a different
    // physical key. A raw setItem would seed a slot nobody reads.
    writeUserScopedRaw(
      STORAGE_KEYS.PROFILE,
      JSON.stringify({ ...FULL, major: mine }),
      captureOwnerToken(),
    );
    loadProfileMock.mockResolvedValue(cloud({ ...FULL, major: theirs }, 8));
    const h = await hydrateProfile();
    expect(h.conflictKeys, 'a real disagreement was published').toEqual(['major']);
    return readCurrentConflicts(['major'], captureOwnerToken());
  }

  /** Whole-accessor recorder: a jsdom method spy on Storage records nothing. */
  function recordStorage() {
    const real = window.localStorage;
    const calls = { get: [] as string[], set: [] as string[], remove: [] as string[] };
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      value: {
        getItem: (k: string) => { calls.get.push(k); return real.getItem(k); },
        setItem: (k: string, v: string) => { calls.set.push(k); real.setItem(k, v); },
        removeItem: (k: string) => { calls.remove.push(k); real.removeItem(k); },
        clear: () => real.clear(),
        key: (i: number) => real.key(i),
        get length() { return real.length; },
      },
    });
    return {
      calls,
      restore: () => Object.defineProperty(
        window, 'localStorage', { configurable: true, value: real },
      ),
    };
  }

  function bytes(): string {
    const out: [string, string][] = [];
    for (let i = 0; i < localStorage.length; i += 1) {
      const k = localStorage.key(i)!;
      out.push([k, localStorage.getItem(k) ?? '']);
    }
    out.sort((a, b) => (a[0] < b[0] ? -1 : 1));
    return JSON.stringify(out);
  }

  function resolveCount() {
    return journalOps().filter((op) => op.mode === 'resolve').length;
  }

  it('O6a: a U1 prompt cannot be answered on a U2 screen', async () => {
    // U1 is shown a real question and never answers it.
    const u1 = captureOwnerToken();
    const u1Question = await questionFor('U1-SECRET', 'Physics');
    const u1View = viewOf({ ...FULL, major: 'U1-SECRET' }, 8, u1);
    const prompt = makeConflictPrompt(u1View, u1Question);

    // U2 takes the browser and has a real accepted view of their OWN row.
    advanceOwnerEpoch('o6-u2');
    await syncLocalIdentityOwner('o6-u2');
    const u2 = captureOwnerToken();
    const u2View = viewOf({ ...FULL, major: 'U2-OWN' }, 3, u2);

    // A server that WOULD accept: the refusal has to come from the resolver's
    // own authority check, not from a mock that answers nothing.
    commitMock.mockReset();
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'U1-SECRET' }, 4));
    const receiptsBefore = resolveCount();
    const before = bytes();
    const rec = recordStorage();
    const answered = await resolveProfileConflict({
      prompt, actionView: u2View, choice: 'local',
    });
    const writes = rec.calls.set;
    rec.restore();

    expect(answered.status, 'an answer assembled from two screens is refused')
      .not.toBe('saved');
    expect(commitMock, 'nothing is sent at all').not.toHaveBeenCalled();
    expect(JSON.stringify(commitMock.mock.calls), "U1's value is in no payload")
      .not.toContain('U1-SECRET');
    expect(resolveCount(), 'and no receipt claims it was decided').toBe(receiptsBefore);
    expect(writes, 'nothing private is written').toEqual([]);
    expect(bytes(), "so U2's bytes are exactly as they were").toBe(before);
  });

  it('O6b: nor a U2 prompt on a U1 screen — the check is not one-directional', async () => {
    const u1 = captureOwnerToken();
    await questionFor('U1-OWN', 'U1-CLOUD');
    const u1View = viewOf({ ...FULL, major: 'U1-SECRET' }, 8, u1);

    // U2 owns the browser and holds the published question.
    advanceOwnerEpoch('o6-u2b');
    await syncLocalIdentityOwner('o6-u2b');
    const u2 = captureOwnerToken();
    const u2Question = await questionFor('U2-OWN', 'U2-CLOUD');
    const prompt = makeConflictPrompt(viewOf({ ...FULL, major: 'U2-OWN' }, 8, u2), u2Question);

    commitMock.mockReset();
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'U1-SECRET' }, 9));
    const receiptsBefore = resolveCount();
    const before = bytes();
    const rec = recordStorage();
    const answered = await resolveProfileConflict({
      prompt, actionView: u1View, choice: 'local',
    });
    const writes = rec.calls.set;
    rec.restore();

    expect(answered.status, 'the current owner cannot answer on a dead screen')
      .not.toBe('saved');
    expect(JSON.stringify(commitMock.mock.calls), "U1's value never leaves under U2")
      .not.toContain('U1-SECRET');
    expect(resolveCount()).toBe(receiptsBefore);
    expect(writes, 'nothing private is written').toEqual([]);
    expect(bytes()).toBe(before);
  });

  it('O6c-control: the SAME view, edited through withRenderedProfile, still answers once', async () => {
    // The control that forbids curing the two above by rejecting everything.
    const token = captureOwnerToken();
    const question = await questionFor('ECE', 'Physics');
    const accepted = viewOf({ ...FULL, major: 'ECE' }, 8, token);
    const prompt = makeConflictPrompt(accepted, question);
    // A normal edit: same viewId, newer rendered document.
    const edited = withRenderedProfile(accepted, { ...FULL, major: 'ECE-EDITED' });
    expect(edited.viewId, 'an edit does not change which view this is')
      .toBe(accepted.viewId);

    commitMock.mockReset();
    commitMock.mockResolvedValueOnce(saved({ ...FULL, major: 'ECE-EDITED' }, 9));
    const answered = await resolveProfileConflict({
      prompt, actionView: edited, choice: 'local',
    });

    expect(answered.status, 'the ordinary path still works').toBe('saved');
    expect(commitMock.mock.calls[0][0].patch,
      'and it sends the value the person could actually see')
      .toEqual({ major: 'ECE-EDITED' });
    expect(commitMock.mock.calls.length, 'exactly one send').toBe(1);
  });

  it('O6d: the same uid at a NEW accepted view is a different capability', async () => {
    const token = captureOwnerToken();
    const question = await questionFor('ECE', 'Physics');
    const prompt = makeConflictPrompt(viewOf({ ...FULL, major: 'ECE' }, 8, token), question);
    // Same person, same values, same revision — but a genuinely new accepted
    // view. The prompt was published for the old one.
    const fresh = viewOf({ ...FULL, major: 'ECE' }, 8, token);
    expect(fresh.viewId, 'a new acceptance is a new view')
      .not.toBe(prompt.originView.viewId);

    commitMock.mockReset();
    commitMock.mockResolvedValue(saved({ ...FULL, major: 'ECE' }, 9));
    const receiptsBefore = resolveCount();
    const rec = recordStorage();
    const answered = await resolveProfileConflict({
      prompt, actionView: fresh, choice: 'local',
    });
    const writes = rec.calls.set;
    rec.restore();

    expect(answered.status, 'a prompt is not transferable between accepted views')
      .not.toBe('saved');
    expect(commitMock, 'nothing is sent').not.toHaveBeenCalled();
    expect(resolveCount(), 'and nothing is recorded').toBe(receiptsBefore);
    expect(writes, 'before any private write').toEqual([]);
  });
});
