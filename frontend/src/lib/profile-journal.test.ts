import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  appendJournalOp,
  clearJournal,
  encodeJournalValue,
  decodeJournalValue,
  hasCrossTabLock,
  readOutstandingOps,
  readRebaseReceipts,
  readAckedOpIds,
  clearJournalKeyGuardForTests,
  registerJournalKeyGuard,
  resetJournalLaneForTests,
  startDocumentForTests,
  settleJournalOps,
  withProfileLock,
  type JournalOp,
} from './profile-journal';
import {
  advanceOwnerEpoch,
  captureOwnerToken,
  syncLocalIdentityOwner,
  USER_SCOPED_PREFIXES,
} from './identity-owner';
import { STORAGE_KEYS } from './storage-keys';

const UID = 'journal-u1';
const PREFIX = STORAGE_KEYS.PROFILE_JOURNAL_PREFIX;

const KNOWN = new Set(['major', 'grade', 'college', 'skills', 'resume_text', 'coursework']);

function op(
  key: string,
  desired: unknown,
  extra: Partial<Omit<JournalOp, 'opId' | 'seq' | 'lineage'>> = {},
): Omit<JournalOp, 'opId' | 'seq' | 'originId' | 'lineage'> {
  return {
    fields: [{ key, base: { present: true, value: 'BASE' }, desired: { present: true, value: desired } }],
    baseRevision: 7,
    writer: 'home-form',
    mode: 'set',
    ...extra,
  };
}
/** The single field of a single-field operation. */
function only(o: JournalOp) { return o.fields[0]; }

function journalKeys(): string[] {
  // localStorage is not a plain object in jsdom — enumerate it properly.
  const out: string[] = [];
  for (let i = 0; i < localStorage.length; i += 1) {
    const key = localStorage.key(i);
    if (key && key.startsWith(PREFIX)) out.push(key);
  }
  return out.sort();
}
function opKeyOf(id: string): string { return `${PREFIX}op_${id}`; }

beforeEach(async () => {
  localStorage.clear();
  resetJournalLaneForTests();
  registerJournalKeyGuard((k) => KNOWN.has(k), ['resume']);
  advanceOwnerEpoch(null);
  advanceOwnerEpoch(UID);
  await syncLocalIdentityOwner(UID);
});

afterEach(() => {
  clearJournalKeyGuardForTests();
});

describe('a lineage never re-issues a sequence it has already used', () => {
  it('a stale positive counter is reconciled against the ops actually stored', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'A' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
    }, token)!;
    const b = appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'B' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
      lineage: a.lineage,
    }, token)!;
    expect(b.seq).toBe(a.seq + 1);

    // The counter write for B silently no-opped: storage still says A's value
    // while the durable op for B exists and records seq 2.
    sessionStorage.setItem('ofe_profile_journal_v1_lineage_seq', String(a.seq));

    // A REAL new document with the same lineage.
    startDocumentForTests('reload');
    const c = appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'C' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
      lineage: a.lineage,
    }, token)!;

    expect(c, 'the append is allowed').toBeTruthy();
    expect(c.seq, 'never a sequence this lineage already used').toBe(b.seq + 1);
    expect(c.seq).not.toBe(b.seq);
  });

  it('refuses to append when the outstanding scan cannot be read', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'A' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
    }, token)!;
    // An unreadable operation makes the whole journal fail closed.
    localStorage.setItem('ofe_profile_journal_v1_op_corrupt', '{not json');
    sessionStorage.removeItem('ofe_profile_journal_v1_lineage_seq');
    startDocumentForTests('reload');
    const before = Object.keys(localStorage).filter((k) => k.includes('journal_v1_op_')).length;

    const blocked = appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'X' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
      lineage: a.lineage,
    }, token);

    expect(blocked, 'safety is indeterminate, so nothing is written').toBeNull();
    expect(Object.keys(localStorage).filter((k) => k.includes('journal_v1_op_')).length)
      .toBe(before);
  });

  it('refuses when the next sequence would leave the safe integer range', () => {
    const token = captureOwnerToken();
    sessionStorage.setItem('ofe_profile_journal_v1_lineage_seq', String(Number.MAX_SAFE_INTEGER));
    startDocumentForTests('reload');
    expect(appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'X' } }],
      baseRevision: 1,
      writer: 'home-form',
      mode: 'set',
    }, token)).toBeNull();
  });
});

describe('a resolution receipt is decoded strictly, from raw storage', () => {
  const PREFIX = 'ofe_profile_journal_v1_op_';

  function writeRaw(op: Record<string, unknown>) {
    localStorage.setItem(`${PREFIX}${op.opId as string}`, JSON.stringify(op));
  }
  function baseReceipt(over: Record<string, unknown> = {}) {
    return {
      opId: 'r1',
      originId: 'o1',
      lineage: 'l1',
      seq: 1,
      baseRevision: 8,
      writer: 'default',
      mode: 'resolve',
      fields: [{ key: 'major', base: { present: true, value: 'A' }, desired: { present: true, value: 'B' } }],
      decisions: { major: 'local' },
      resolvesPending: { mutationId: 'm1', keyVersions: { major: 1 } },
      ...over,
    };
  }

  it('accepts a well-formed pending-only receipt', () => {
    writeRaw(baseReceipt());
    const read = readOutstandingOps();
    expect(read.ok).toBe(true);
    expect(read.ok && read.value[0].resolvesPending)
      .toEqual({ mutationId: 'm1', keyVersions: { major: 1 } });
  });

  it('refuses a duplicated field key', () => {
    writeRaw(baseReceipt({
      fields: [
        { key: 'major', base: { present: false }, desired: { present: true, value: 'B' } },
        { key: 'major', base: { present: false }, desired: { present: true, value: 'C' } },
      ],
    }));
    expect(readOutstandingOps().ok, 'which decision belongs to which field?').toBe(false);
  });

  it('refuses partial pending coverage when there are no operation ids', () => {
    writeRaw(baseReceipt({
      fields: [
        { key: 'major', base: { present: false }, desired: { present: true, value: 'B' } },
        { key: 'college', base: { present: false }, desired: { present: true, value: 'C' } },
      ],
      decisions: { major: 'local', college: 'local' },
      resolvesPending: { mutationId: 'm1', keyVersions: { major: 1 } },
    }));
    expect(readOutstandingOps().ok, 'college is bound by nothing at all').toBe(false);
  });

  it('refuses an unknown property inside the pending target', () => {
    writeRaw(baseReceipt({
      resolvesPending: { mutationId: 'm1', keyVersions: { major: 1 }, scope: 'future' },
    }));
    expect(readOutstandingOps().ok, 'a newer build meant something by it').toBe(false);
  });

  it('refuses an operation whose seq is beyond the safe integer range', () => {
    writeRaw(baseReceipt({ seq: Number.MAX_SAFE_INTEGER + 1 }));
    expect(readOutstandingOps().ok, 'seq orders this lineage: it cannot alias').toBe(false);
  });

  it('refuses an operation whose baseRevision is beyond the safe integer range', () => {
    writeRaw(baseReceipt({ baseRevision: Number.MAX_SAFE_INTEGER + 1 }));
    expect(readOutstandingOps().ok, 'baseRevision is compared for equality').toBe(false);
  });

  it('refuses a negative seq', () => {
    writeRaw(baseReceipt({ seq: -1 }));
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('refuses a rebase receipt whose revision is beyond the safe integer range', () => {
    localStorage.setItem(
      'ofe_profile_journal_v1_rebase_anc1',
      JSON.stringify({
        v: 1,
        ancestorOpId: 'anc1',
        ancestorLineage: 'l1',
        revision: Number.MAX_SAFE_INTEGER + 1,
        profile: { major: { present: true, value: 'CS' } },
        confirmedKeys: ['major'],
      }),
    );
    expect(readRebaseReceipts().ok).toBe(false);
  });

  it('refuses a version beyond the safe integer range', () => {
    // 2^53 and 2^53+1 parse to the SAME double. A tuple comparison built on
    // them would match two different questions.
    writeRaw(baseReceipt({
      resolvesPending: { mutationId: 'm1', keyVersions: { major: Number.MAX_SAFE_INTEGER + 1 } },
    }));
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('refuses a negative version', () => {
    writeRaw(baseReceipt({ resolvesPending: { mutationId: 'm1', keyVersions: { major: -1 } } }));
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('refuses a non-integer version', () => {
    writeRaw(baseReceipt({ resolvesPending: { mutationId: 'm1', keyVersions: { major: 1.5 } } }));
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('refuses an ORDINARY operation carrying a pending target', () => {
    writeRaw(baseReceipt({ mode: 'set', decisions: undefined }));
    expect(readOutstandingOps().ok, 'only a receipt may name what it did not write').toBe(false);
  });
});

describe('the journal is durable at edit time', () => {
  it('an append is on disk immediately — no debounce, no batching', () => {
    const token = captureOwnerToken();
    const written = appendJournalOp(op('major', 'ECE'), token);
    expect(written).not.toBeNull();

    // A crash here loses nothing: the operation is already a stored value.
    const outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(true);
    expect(outstanding.ok && outstanding.value).toHaveLength(1);
    expect(outstanding.ok && outstanding.value[0].fields[0].desired.value).toBe('ECE');
    expect(outstanding.ok && outstanding.value[0].baseRevision).toBe(7);
  });

  it('records PRESENCE, so "the field had no value" is not the same as "we forgot"', () => {
    const source: Record<string, unknown> = { major: 'CS', grade: undefined };
    expect(encodeJournalValue(source, 'major')).toEqual({ present: true, value: 'CS' });
    expect(encodeJournalValue(source, 'grade')).toEqual({ present: false });
    expect(encodeJournalValue(source, 'nothing_here')).toEqual({ present: false });

    const token = captureOwnerToken();
    appendJournalOp({
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'ECE' } }],
      baseRevision: 7, writer: 'home-form', mode: 'set',
    }, token);
    const outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(true);
    // Survives the JSON round trip as an explicit absence, not a dropped key.
    const stored = outstanding.ok ? outstanding.value[0] : null;
    expect(only(stored!).base).toEqual({ present: false });
    expect(decodeJournalValue(only(stored!).base)).toBeUndefined();
  });

  it('a stale owner appends nothing', async () => {
    const stale = captureOwnerToken();
    advanceOwnerEpoch('journal-u2');
    await syncLocalIdentityOwner('journal-u2');
    expect(appendJournalOp(op('major', 'ECE'), stale)).toBeNull();
    expect(journalKeys()).toEqual([]);
  });

  it('the lanes are cleared on an account switch', () => {
    // They hold one identity's unsent edits under fixed key names.
    expect(USER_SCOPED_PREFIXES).toContain(PREFIX);
  });
});

describe('two tabs never lose each other\'s operations', () => {
  it('every append is its OWN key — there is no shared value to interleave', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp(op('major', 'from tab A'), token)!;
    // A second tab: same storage, and it does not read or rewrite anything A
    // wrote — it just creates a key of its own.
    resetJournalLaneForTests();
    const b = appendJournalOp(op('grade', 'from tab B'), token)!;
    expect(a.opId).not.toBe(b.opId);
    expect(journalKeys()).toEqual([opKeyOf(a.opId), opKeyOf(b.opId)].sort());

    const outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(true);
    const values = outstanding.ok ? outstanding.value.map((o) => only(o).desired.value).sort() : [];
    expect(values).toEqual(['from tab A', 'from tab B']);
  });

  it('THE INTERLEAVING MUTANT: an append landing DURING a settle survives it', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp(op('major', 'A'), token)!;

    // The consolidating tab has read the journal and is about to settle A.
    const seen = readOutstandingOps();
    expect(seen.ok && seen.value.map((o) => o.opId)).toEqual([a.opId]);

    // Another tab appends B in that window. It does not take the lock — it
    // never needs to — so this is the exact race an array lane would lose.
    resetJournalLaneForTests();
    const b = appendJournalOp(op('grade', 'B'), token)!;

    // The settle completes, acting ONLY on the id it was given.
    expect(settleJournalOps([a.opId], token)).toBe(true);

    const after = readOutstandingOps();
    expect(after.ok && after.value.map((o) => o.opId)).toEqual([b.opId]);
    expect(localStorage.getItem(opKeyOf(a.opId))).toBeNull();
    expect(localStorage.getItem(opKeyOf(b.opId))).not.toBeNull();
  });

  it('a tab appending the SAME key twice keeps both operations', () => {
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'first'), token);
    appendJournalOp(op('major', 'second'), token);
    const outstanding = readOutstandingOps();
    expect(outstanding.ok && outstanding.value.map((o) => only(o).desired.value).sort())
      .toEqual(['first', 'second']);
  });

  it('enumeration order is NOT a happens-before relation across tabs', () => {
    // Both tabs edited `major` from the same base. Nothing about the storage
    // order says whose edit came first, which is why the caller must resolve
    // them by their frozen bases rather than taking the last one read.
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'tab A wants ECE'), token);
    resetJournalLaneForTests();
    appendJournalOp(op('major', 'tab B wants Physics'), token);
    const outstanding = readOutstandingOps();
    expect(outstanding.ok && outstanding.value).toHaveLength(2);
    const bases = outstanding.ok ? outstanding.value.map((o) => only(o).base.value) : [];
    expect(bases).toEqual(['BASE', 'BASE']); // same base — a genuine conflict
  });
});

describe('fail closed — never filter', () => {
  it('a malformed operation makes every cross-tab read fail, and is NOT deleted', () => {
    const token = captureOwnerToken();
    const good = appendJournalOp(op('major', 'keep me'), token)!;
    const before = localStorage.getItem(opKeyOf(good.opId));
    localStorage.setItem(`${PREFIX}op_corrupt`, '{not json');

    const outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(false);
    expect(!outstanding.ok && outstanding.reason).toMatch(/JSON/);
    expect(localStorage.getItem(opKeyOf(good.opId))).toBe(before);
    expect(localStorage.getItem(`${PREFIX}op_corrupt`)).toBe('{not json');
  });

  it('an operation naming an UNKNOWN key or mode fails the read — a downgrade cannot drop it', () => {
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'mine'), token);

    localStorage.setItem(`${PREFIX}op_x1`, JSON.stringify({
      opId: 'x1', originId: 'other-tab', lineage: 'other-tab', fields: [{ key: 'a_field_from_the_future', base: { present: false }, desired: { present: true, value: 1 } }],
      baseRevision: 7,
      writer: 'home-form', mode: 'set', seq: 1,
    }));
    let outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(false);
    expect(!outstanding.ok && outstanding.reason).toMatch(/unknown profile key/);
    localStorage.removeItem(`${PREFIX}op_x1`);

    localStorage.setItem(`${PREFIX}op_x2`, JSON.stringify({
      opId: 'x2', originId: 'other-tab', lineage: 'other-tab', fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 1 } }],
      baseRevision: 7,
      writer: 'home-form', mode: 'merge-somehow', seq: 1,
    }));
    outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(false);
    expect(!outstanding.ok && outstanding.reason).toMatch(/unknown operation mode/);
  });

  it('an unregistered key guard fails every read — it does not assume "probably fine"', () => {
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'mine'), token);
    clearJournalKeyGuardForTests();
    const outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(false);
    expect(!outstanding.ok && outstanding.reason).toMatch(/guard/);
  });

  it('a failed enumeration is a failure, not an empty journal', () => {
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'mine'), token);
    const spy = vi.spyOn(window.localStorage, 'key').mockImplementation(() => {
      throw new Error('enumeration denied');
    });
    const outstanding = readOutstandingOps();
    spy.mockRestore();
    expect(outstanding.ok).toBe(false);
    expect(!outstanding.ok && outstanding.reason).toMatch(/enumeration/);
  });

  it('a malformed ack set fails rather than re-sending everything', () => {
    localStorage.setItem(`${PREFIX}ack`, '{"not":"a list"}');
    expect(readAckedOpIds().ok).toBe(false);
    expect(readOutstandingOps().ok).toBe(false);
  });
});

describe('acknowledgement is two-phase and bounded', () => {
  it('an acked operation is removed, and the ack set with it', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp(op('major', 'A'), token)!;
    expect(settleJournalOps([a.opId], token)).toBe(true);
    expect(localStorage.getItem(opKeyOf(a.opId))).toBeNull();
    expect(localStorage.getItem(`${PREFIX}ack`)).toBeNull();
  });

  it('the ack is written BEFORE the delete, so a delete that fails does not re-send', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp(op('major', 'A'), token)!;
    // Storage that silently refuses to remove — the exact case the two-phase
    // order exists for.
    const spy = vi.spyOn(window.localStorage, 'removeItem').mockImplementation(() => {});
    // NOT a success. The write is safe — the ack landed first, so it is never
    // sent twice — but the operation is still on disk and something has to
    // come back for it. Reporting `true` here is what left it there for good:
    // readers skip acked ids, so nothing can ever rediscover it as work.
    expect(settleJournalOps([a.opId], token)).toBe(false);
    spy.mockRestore();

    // The operation is still on disk, but it is ACKED — so it is not
    // outstanding, and the write it describes is never sent twice.
    expect(localStorage.getItem(opKeyOf(a.opId))).not.toBeNull();
    const outstanding = readOutstandingOps();
    expect(outstanding.ok && outstanding.value).toEqual([]);
    expect(JSON.parse(localStorage.getItem(`${PREFIX}ack`)!)).toEqual([a.opId]);
  });

  it('phase one alone is what survives a crash before the final ack write', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp(op('major', 'A'), token)!;
    const realSet = window.localStorage.setItem.bind(window.localStorage);
    // The process dies the moment the deletes begin: any ack write attempted
    // AFTER that point never lands. Only an ack written BEFORE the deletes
    // survives — which is the whole reason for the ordering.
    let deletesStarted = false;
    const removeSpy = vi.spyOn(window.localStorage, 'removeItem').mockImplementation(() => {
      deletesStarted = true;
    });
    const setSpy = vi.spyOn(window.localStorage, 'setItem').mockImplementation((k: string, v: string) => {
      if (k === `${PREFIX}ack` && deletesStarted) return;
      realSet(k, v);
    });
    settleJournalOps([a.opId], token);
    removeSpy.mockRestore();
    setSpy.mockRestore();

    // Only the ack written BEFORE the deletes is on disk. Without it, this
    // operation would be outstanding again and its write sent a second time.
    expect(JSON.parse(localStorage.getItem(`${PREFIX}ack`)!)).toEqual([a.opId]);
    const outstanding = readOutstandingOps();
    expect(outstanding.ok && outstanding.value).toEqual([]);
  });

  it('a non-integer or negative seq is refused', () => {
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'mine'), token);
    for (const seq of [1.5, -1]) {
      localStorage.setItem(`${PREFIX}op_seq`, JSON.stringify({
        opId: 'seq', originId: 'other-tab', lineage: 'other-tab', fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 1 } }],
        baseRevision: 7, writer: 'home-form', mode: 'set', seq,
      }));
      const outstanding = readOutstandingOps();
      expect(outstanding.ok).toBe(false);
      expect(!outstanding.ok && outstanding.reason).toMatch(/malformed/);
    }
  });

  it('a storage key that does not match the operation inside it is refused', () => {
    const token = captureOwnerToken();
    const real = appendJournalOp(op('major', 'the real one'), token)!;
    // A key claiming to hold a DIFFERENT operation. Honouring it would let a
    // settle of 'imposter' delete the real operation's key instead.
    localStorage.setItem(`${PREFIX}op_imposter`, JSON.stringify({
      opId: real.opId, originId: 'other-tab', lineage: 'other-tab', fields: [{ key: 'grade', base: { present: false }, desired: { present: true, value: 'x' } }],
      baseRevision: 7, writer: 'home-form', mode: 'set', seq: 1,
    }));
    const outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(false);
    expect(!outstanding.ok && outstanding.reason).toMatch(/does not match its own opId/);
  });

  it('an operation with an unknown bundle is refused — grouping is semantics', () => {
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'mine'), token);
    localStorage.setItem(`${PREFIX}op_b1`, JSON.stringify({
      opId: 'b1', originId: 'other-tab', lineage: 'other-tab', fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 1 } }],
      baseRevision: 7, writer: 'home-form', mode: 'set',
      seq: 1, bundle: 'some-future-bundle',
    }));
    const outstanding = readOutstandingOps();
    expect(outstanding.ok).toBe(false);
    expect(!outstanding.ok && outstanding.reason).toMatch(/unknown operation bundle/);
  });

  it('a crash between the two phases leaves an acked operation, which readers SKIP', () => {
    const token = captureOwnerToken();
    const a = appendJournalOp(op('major', 'A'), token)!;
    const b = appendJournalOp(op('grade', 'B'), token)!;
    // Phase one landed; phase two never ran.
    localStorage.setItem(`${PREFIX}ack`, JSON.stringify([a.opId]));

    const outstanding = readOutstandingOps();
    expect(outstanding.ok && outstanding.value.map((o) => o.opId)).toEqual([b.opId]);

    // The next settle finishes the job — never the reverse order, which would
    // lose the ack and re-send a write that already landed.
    expect(settleJournalOps([a.opId], token)).toBe(true);
    expect(localStorage.getItem(opKeyOf(a.opId))).toBeNull();
  });

  it('an abandoned tab\'s operations are collected without its help', () => {
    const token = captureOwnerToken();
    localStorage.setItem(`${PREFIX}op_gone-1`, JSON.stringify({
      opId: 'gone-1', originId: 'other-tab', lineage: 'other-tab', fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: 'x' } }],
      baseRevision: 7, writer: 'home-form', mode: 'set', seq: 1,
    }));
    localStorage.setItem(`${PREFIX}op_gone-2`, JSON.stringify({
      opId: 'gone-2', originId: 'other-tab', lineage: 'other-tab', fields: [{ key: 'grade', base: { present: false }, desired: { present: true, value: 'y' } }],
      baseRevision: 7, writer: 'home-form', mode: 'set', seq: 2,
    }));
    expect(settleJournalOps(['gone-1'], token)).toBe(true);
    const rest = readOutstandingOps();
    expect(rest.ok && rest.value.map((o) => o.opId)).toEqual(['gone-2']);
    expect(localStorage.getItem(`${PREFIX}op_gone-1`)).toBeNull();
  });

  it('the journal refuses to grow without bound', { timeout: 20000 }, () => {
    const token = captureOwnerToken();
    let appended = 0;
    for (let i = 0; i < 520; i += 1) {
      if (appendJournalOp(op('major', `v${i}`), token)) appended += 1;
    }
    expect(appended).toBe(500);
    expect(appendJournalOp(op('major', 'over'), token)).toBeNull();
  });

  it('clearJournal removes everything', () => {
    const token = captureOwnerToken();
    appendJournalOp(op('major', 'A'), token);
    resetJournalLaneForTests();
    appendJournalOp(op('grade', 'B'), token);
    expect(clearJournal(token)).toBe(true);
    expect(journalKeys()).toEqual([]);
  });
});

describe('the cross-tab lock', () => {
  const originalLocks = (navigator as unknown as { locks?: unknown }).locks;

  function installLock(): { held: string[] } {
    const held: string[] = [];
    let chain: Promise<unknown> = Promise.resolve();
    Object.defineProperty(navigator, 'locks', {
      configurable: true,
      value: {
        request: (name: string, _opts: unknown, fn: () => Promise<unknown>) => {
          held.push(name);
          const run = chain.then(() => fn());
          chain = run.then(() => undefined, () => undefined);
          return run;
        },
      },
    });
    return { held };
  }

  afterEach(() => {
    Object.defineProperty(navigator, 'locks', { configurable: true, value: originalLocks });
  });

  it('is ONE name for every account — the keys it guards are not uid-scoped', async () => {
    const { held } = installLock();
    const t1 = captureOwnerToken();
    await withProfileLock(t1, () => 1);
    advanceOwnerEpoch('journal-u2');
    await syncLocalIdentityOwner('journal-u2');
    await withProfileLock(captureOwnerToken(), () => 2);
    expect(new Set(held).size).toBe(1);
  });

  it('serializes two holders', async () => {
    installLock();
    const token = captureOwnerToken();
    const order: string[] = [];
    let releaseFirst!: () => void;
    const first = withProfileLock(token, () => new Promise<void>((r) => {
      order.push('a-start');
      releaseFirst = () => { order.push('a-end'); r(); };
    }));
    const second = withProfileLock(token, () => { order.push('b'); });
    await Promise.resolve();
    expect(order).toEqual(['a-start']); // b is waiting
    releaseFirst();
    await Promise.all([first, second]);
    expect(order).toEqual(['a-start', 'a-end', 'b']);
  });

  it('an identity change WHILE waiting is SUPERSEDED, not this owner\'s failure', async () => {
    installLock();
    const token = captureOwnerToken();
    let releaseFirst!: () => void;
    const blocking = withProfileLock(token, () => new Promise<void>((r) => { releaseFirst = r; }));
    await Promise.resolve(); // the fake lock invokes fn on a microtask
    let ran = false;
    const queued = withProfileLock(token, () => { ran = true; });

    // The account switches while the second call is still queued. The epoch
    // fence lands synchronously; the namespace transition takes THIS lock, so
    // it cannot complete until the holder lets go — awaiting it before the
    // release would deadlock, which is the guarantee, not a test bug.
    advanceOwnerEpoch('journal-u2');
    const transition = syncLocalIdentityOwner('journal-u2');
    releaseFirst();
    await blocking;
    await transition;
    const result = await queued;

    expect(ran).toBe(false);
    expect(result.ok).toBe(false);
    // Somebody else owns the browser now, so this call's news is nobody's and
    // it is dropped in silence. Reporting it as 'abandoned' — this owner's own
    // unconfirmed realm — would surface an error banner about an account that
    // has already left the screen.
    expect(!result.ok && result.reason).toBe('superseded');
  });

  it('a still-current owner whose realm is unconfirmed is ABANDONED — its own failure, reported', async () => {
    installLock();
    // Same uid and epoch, but the local realm was never confirmed ready.
    advanceOwnerEpoch('journal-unconfirmed');
    const token = captureOwnerToken();
    let ran = false;
    const result = await withProfileLock(token, () => { ran = true; });
    expect(ran, 'the body never runs').toBe(false);
    expect(!result.ok && result.reason).toBe('abandoned');
  });

  it('a stale token with NO Web Locks is superseded, decided before the lock manager is even consulted', async () => {
    const token = captureOwnerToken();
    advanceOwnerEpoch('journal-nolock-u2');
    await syncLocalIdentityOwner('journal-nolock-u2');
    // No lock manager at all.
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    let ran = false;
    const result = await withProfileLock(token, () => { ran = true; });
    expect(ran).toBe(false);
    // 'no-lock' would send every caller into its one-snapshot fallback, which
    // reads the CURRENT owner's state on behalf of an owner who is gone.
    expect(!result.ok && result.reason).toBe('superseded');
  });

  it('a fully valid token with no Web Locks is NO-LOCK — the environment, not the identity', async () => {
    advanceOwnerEpoch('journal-nolock-ok');
    await syncLocalIdentityOwner('journal-nolock-ok');
    const token = captureOwnerToken();
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    let ran = false;
    const result = await withProfileLock(token, () => { ran = true; });
    expect(ran).toBe(false);
    expect(!result.ok && result.reason).toBe('no-lock');
  });

  it('without a lock manager it fails closed — it does not proceed unserialized', async () => {
    Object.defineProperty(navigator, 'locks', { configurable: true, value: undefined });
    expect(hasCrossTabLock()).toBe(false);
    let ran = false;
    const result = await withProfileLock(captureOwnerToken(), () => { ran = true; });
    expect(ran).toBe(false);
    expect(result.ok).toBe(false);
    expect(!result.ok && result.reason).toBe('no-lock');
  });
});

describe('ancestry that could not have been written honestly is refused', () => {
  function raw(id: string, extra: Record<string, unknown>) {
    localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_${id}`, JSON.stringify({
      opId: id,
      originId: 'o', lineage: 'L1',
      fields: [{ key: 'major', base: { present: false }, desired: { present: true, value: id } }],
      baseRevision: 1, writer: 'home-form', mode: 'set', seq: 1,
      ...extra,
    }));
  }

  it('an operation that supersedes ITSELF is refused', () => {
    raw('self', { supersedes: ['self'] });
    const read = readOutstandingOps();
    expect(read.ok).toBe(false);
  });

  it('a cycle within one lineage is refused', () => {
    raw('cyc1', { supersedes: ['cyc2'], seq: 1 });
    raw('cyc2', { supersedes: ['cyc1'], seq: 2 });
    const read = readOutstandingOps();
    expect(read.ok).toBe(false);
  });

  it('claiming ancestry over ANOTHER lineage is refused', () => {
    raw('other', { lineage: 'L2', seq: 1 });
    raw('thief', { supersedes: ['other'], seq: 2 });
    const read = readOutstandingOps();
    expect(read.ok).toBe(false);
  });

  it('an ORDINARY edit that claims to answer another operation is refused', () => {
    // Only a receipt may speak for operations it did not write. An ordinary
    // edit carrying `resolves` is either corrupt or forged.
    raw('plain', { resolves: ['whatever'] });
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('a receipt with no decision for a field it carries is refused', () => {
    raw('halfR', { mode: 'resolve', resolves: ['x'], decisions: {} });
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('a receipt deciding a field it does not carry is refused', () => {
    raw('wideR', { mode: 'resolve', resolves: ['x'], decisions: { major: 'local', grade: 'cloud' } });
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('a receipt with an unknown decision is refused', () => {
    raw('badR', { mode: 'resolve', resolves: ['x'], decisions: { major: 'whatever' } });
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('a receipt whose fields are not fields fails CLOSED rather than throwing', () => {
    localStorage.setItem(`${STORAGE_KEYS.PROFILE_JOURNAL_PREFIX}op_nulls`, JSON.stringify({
      opId: 'nulls', originId: 'o', lineage: 'L1',
      fields: [null], baseRevision: 1, writer: 'home-form', mode: 'resolve',
      seq: 1, resolves: ['x'], decisions: { major: 'local' },
    }));
    expect(() => readOutstandingOps()).not.toThrow();
    expect(readOutstandingOps().ok).toBe(false);
  });

  it('a supersedes id that is simply gone is not ancestry to check', () => {
    // The ordinary case: the ancestor was acknowledged and removed. Nothing
    // to verify, and nothing wrong.
    raw('lone', { supersedes: ['already-acknowledged'] });
    const read = readOutstandingOps();
    expect(read.ok).toBe(true);
    expect(read.ok && read.value).toHaveLength(1);
  });
});


describe('an operation can never cross from one account to another', () => {
  it('a late append fails closed once ANOTHER realm has swept the browser to a new owner', () => {
    // Two module realms, one browser. This one still believes it is U1 —
    // its auth event has not arrived — while the other has already switched
    // the shared owner marker to U2 and cleared U1's keys. A write that only
    // consults this realm's own memory would land U1's bytes in U2's browser,
    // under a fixed key, with nothing on them to say whose they are.
    const token = captureOwnerToken();
    expect(appendJournalOp(op('major', 'mine'), token), 'sanity: writable as U1').toBeTruthy();

    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'sweeper-u2');

    expect(appendJournalOp(op('major', 'late'), token)).toBeNull();
  });

  it('bytes left behind by a previous owner are not readable as the new one', () => {
    const token = captureOwnerToken();
    expect(appendJournalOp(op('major', 'u1 wrote this'), token)).toBeTruthy();
    expect(readOutstandingOps().ok).toBe(true);

    // The sweep misses one key — a crash, a quota error, a late write. The
    // new owner must not be able to read it, let alone replay it.
    localStorage.setItem(STORAGE_KEYS.LOCAL_IDENTITY_OWNER, 'sweeper-u2');
    const read = readOutstandingOps();
    expect(read.ok && read.value.some(
      (o) => o.fields.some((f) => f.desired.present && f.desired.value === 'u1 wrote this'),
    )).toBe(false);
  });
});
