'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { captureOwnerToken, isOwnerTokenValid, isTokenOwnerStillCurrent, onLocalOwnerStateChange, type OwnerToken } from './identity-owner';
import { createColdEmailDraftWriter, readColdEmailDraft, type ColdEmailDraftPayload, type ColdEmailDraftWriteResult } from './cold-email-draft';

type Status = 'idle' | 'saving' | 'saved' | 'failed' | 'conflict';
type Writer = ReturnType<typeof createColdEmailDraftWriter>;
type Session = {
  key: string; owner: OwnerToken; id: string; writer: Writer | null;
  /** Undefined means the initial read failed: no revision was observed. */
  revision: string | null | undefined;
  payload: ColdEmailDraftPayload | null; serialized: string | null;
  status: Status; issue: string | null; sequence: number; listeners: Set<() => void>;
  retired: boolean; blockedInput: boolean; clearing: boolean; retrying: Promise<boolean> | null;
};
// Only unfinished/failed work survives SPA unmount. Durable success is reread
// from storage. Retired owner sessions and abandoned editors never re-enter.
const unfinished = new Map<string, Session>();
const ownerKey = (owner: OwnerToken, id: string) => JSON.stringify([owner.uid, owner.epoch, owner.generation, id]);
function issue(error: unknown): string {
  return error && typeof error === 'object' && 'code' in error ? String(error.code) : 'storage_unavailable';
}
function forget(session: Session) { if (unfinished.get(session.key) === session) unfinished.delete(session.key); }
function sameOwner(session: Session) {
  return isTokenOwnerStillCurrent(session.owner) && captureOwnerToken().generation === session.owner.generation;
}
function retire(session: Session) {
  session.retired = true; session.sequence += 1; session.payload = null; session.serialized = null; forget(session);
}
function usable(session: Session) {
  if (session.retired) return false;
  if (!sameOwner(session)) { retire(session); return false; }
  return isOwnerTokenValid(session.owner, session.owner.uid);
}
function publish(session: Session) {
  if (!usable(session)) { forget(session); return; }
  if (session.status === 'saved' || session.status === 'idle') forget(session);
  else unfinished.set(session.key, session);
  for (const listener of session.listeners) listener();
}
function received(session: Session, writer: Writer, sequence: number, result: ColdEmailDraftWriteResult) {
  if (!usable(session) || session.writer !== writer) { forget(session); return; }
  // Even an older successful edit advances this writer's base revision. It
  // must not overwrite the status of a newer edit or failed panel snapshot.
  if (result.status !== 'conflict') session.revision = result.revision;
  if (sequence !== session.sequence) return;
  session.status = result.status === 'conflict' ? 'conflict' : 'saved';
  session.issue = result.status === 'conflict' ? 'conflict' : null;
  publish(session);
}
function rejected(session: Session, writer: Writer, sequence: number, error: unknown) {
  if (!usable(session) || session.writer !== writer) { forget(session); return; }
  if (sequence !== session.sequence) return;
  session.status = 'failed'; session.issue = issue(error); publish(session);
}
function save(session: Session) {
  const writer = session.writer; const payload = session.payload;
  if (!writer || !payload || !usable(session)) return;
  const sequence = ++session.sequence;
  session.status = 'saving'; session.issue = null; publish(session);
  void writer.save(payload).then(result => received(session, writer, sequence, result), error => rejected(session, writer, sequence, error));
}

/** Owner-bound editing lifetime. Restoring text does not restore send attestations. */
export function useColdEmailDraftPersistence() {
  const active = useRef<Session | null>(null);
  const [view, setView] = useState<{ status: Status; issue: string | null }>({ status: 'idle', issue: null });
  const update = useCallback(() => {
    const session = active.current;
    if (!session) return;
    if (!sameOwner(session) || session.retired) {
      retire(session); active.current = null; setView({ status: 'idle', issue: null });
    } else if (usable(session)) setView({ status: session.status, issue: session.issue });
  }, []);
  const detach = useCallback(() => {
    active.current?.listeners.delete(update);
    active.current = null;
  }, [update]);
  useEffect(() => {
    const unsubscribe = onLocalOwnerStateChange(update);
    return () => { unsubscribe(); detach(); };
  }, [detach, update]);

  const open = useCallback((id: string): { draft: ColdEmailDraftPayload | null; restored: boolean } => {
    detach();
    const owner = captureOwnerToken(); const key = ownerKey(owner, id);
    // Also retire detached sessions from older identities; late promises may
    // otherwise keep private text alive without an attached React listener.
    for (const cached of unfinished.values()) if (!sameOwner(cached)) retire(cached);
    let session = unfinished.get(key);
    if (session && !usable(session)) { forget(session); session = undefined; }
    if (!session) {
      session = { key, owner, id, writer: null, revision: undefined, payload: null, serialized: null,
        status: 'idle', issue: null, sequence: 0, listeners: new Set(), retired: false, blockedInput: false, clearing: false, retrying: null };
      try {
        const stored = readColdEmailDraft(owner, id);
        session.revision = stored.revision; session.writer = createColdEmailDraftWriter(owner, id, stored.revision);
        if (stored.status === 'present') {
          session.payload = stored.draft; session.serialized = JSON.stringify(stored.draft); session.status = 'saved';
        }
      } catch (error) { session.status = 'failed'; session.issue = issue(error); }
    }
    active.current = session; session.listeners.add(update);
    setView({ status: session.status, issue: session.issue });
    // Consumers edit their own copy, never the recovery session's snapshot.
    return { draft: session.payload ? JSON.parse(JSON.stringify(session.payload)) as ColdEmailDraftPayload : null, restored: !!session.payload };
  }, [detach, update]);

  const persist = useCallback((payload: ColdEmailDraftPayload) => {
    const session = active.current;
    if (!session || !usable(session)) return;
    let serialized: string;
    try { serialized = JSON.stringify(payload); } catch {
      session.sequence += 1; session.blockedInput = true; session.status = 'failed'; session.issue = 'invalid_draft'; publish(session); return;
    }
    const changed = serialized !== session.serialized;
    const wasBlocked = session.blockedInput;
    session.blockedInput = false;
    if (!changed && !wasBlocked) return;
    // Keep even an over-limit typed snapshot in memory. The store validates it
    // and fails visibly; no truncation, discarded text, or automatic retry.
    session.payload = JSON.parse(serialized) as ColdEmailDraftPayload; session.serialized = serialized;
    session.sequence += 1;
    if (session.clearing || !session.writer || session.status === 'failed' || session.status === 'conflict') {
      session.status = session.status === 'conflict' ? 'conflict' : 'failed';
      session.issue ??= 'storage_unavailable'; publish(session); return;
    }
    save(session);
  }, []);

  const markUnsaved = useCallback((reason: string) => {
    const session = active.current;
    if (!session || !usable(session)) return;
    session.sequence += 1; session.blockedInput = true;
    session.status = 'failed'; session.issue = reason; publish(session);
  }, []);
  const flush = useCallback(async (): Promise<boolean> => {
    const session = active.current;
    if (!session || !usable(session) || session.clearing) return false;
    if (!session.writer) return session.payload === null && session.status === 'idle';
    const sequence = session.sequence; const writer = session.writer;
    try { await writer.flush(); } catch (error) {
      if (!session.blockedInput) rejected(session, writer, sequence, error);
      return false;
    }
    return active.current === session && sequence === session.sequence && usable(session) && !session.blockedInput
      && (session.status === 'saved' || session.status === 'idle');
  }, []);
  const retry = useCallback((): Promise<boolean> => {
    const session = active.current;
    if (!session || !usable(session) || session.clearing || session.blockedInput) return Promise.resolve(false);
    if (session.retrying) return session.retrying;
    const run = async () => {
      const previous = session.writer;
      // Successful writes queued before the failure still establish revisions.
      // Never race a new writer against this editor's older writes.
      try { await previous?.flush(); } catch { /* The failure is what retry resolves. */ }
      if (active.current !== session || !usable(session) || session.blockedInput || session.clearing) return false;
      if (session.revision === undefined) {
        try {
          const stored = readColdEmailDraft(session.owner, session.id);
          if (stored.status === 'present') {
            session.status = 'conflict'; session.issue = 'conflict'; publish(session); return false;
          }
          session.revision = stored.revision;
        } catch (error) { session.status = 'failed'; session.issue = issue(error); publish(session); return false; }
      }
      session.writer = createColdEmailDraftWriter(session.owner, session.id, session.revision);
      if (!session.payload) { session.status = 'idle'; session.issue = null; publish(session); return true; }
      save(session);
      const writer = session.writer; const sequence = session.sequence;
      try {
        await writer.flush();
      } catch (error) { rejected(session, writer, sequence, error); return false; }
      return active.current === session && usable(session) && sequence === session.sequence
        && session.status === 'saved' && !session.blockedInput;
    };
    session.retrying = run().finally(() => { session.retrying = null; });
    return session.retrying;
  }, []);
  const clear = useCallback(async (): Promise<boolean> => {
    const session = active.current;
    if (!session || !session.writer || !usable(session) || session.clearing) return false;
    // A new edit during flush cancels the delete, rather than deleting unseen work.
    if (!await flush() || active.current !== session || !usable(session) || session.clearing) return false;
    const writer = session.writer; const sequence = ++session.sequence;
    session.clearing = true; session.status = 'saving'; session.issue = null; publish(session);
    try {
      const result = await writer.delete();
      if (!usable(session)) return false;
      if (result.status === 'conflict') { session.status = 'conflict'; session.issue = 'conflict'; publish(session); return false; }
      session.revision = result.revision;
      session.writer = createColdEmailDraftWriter(session.owner, session.id, result.revision);
      if (sequence !== session.sequence) {
        session.status = 'failed'; session.issue = 'draft_changed'; publish(session); return false;
      }
      // Successful deletion ends this editing lifetime. Only open() starts a
      // new one; a captured old persist callback cannot resurrect the payload.
      const attached = active.current === session;
      retire(session);
      if (attached) { detach(); setView({ status: 'idle', issue: null }); }
      return attached;
    } catch (error) {
      if (usable(session)) { session.status = 'failed'; session.issue = issue(error); publish(session); }
      return false;
    } finally { session.clearing = false; }
  }, [flush, detach]);
  const abandon = useCallback(() => {
    const session = active.current; if (session) retire(session);
    detach(); setView({ status: 'idle', issue: null });
  }, [detach]);
  return { open, persist, flush, clear, detach, abandon, retry, markUnsaved, status: view.status, issue: view.issue };
}
