'use client';

import { useEffect, useLayoutEffect, useRef } from 'react';
import { captureOwnerToken, isOwnerTokenValid, type OwnerToken } from '@/lib/identity-owner';

const MODAL_STATE = '__ofeResultsModal';
// Closed cards must not remove the history marker owned by another live card.
const activeEntries = new Set<string>();

/** A request handles closure itself; false means the editor kept its draft and
 * displayed its existing discard confirmation. */
export type ModalCloseRequest = () => boolean;

/** Back requests closure of a results overlay. It never changes the tracker. */
export function useResultModalHistory(
  open: boolean,
  onClose: () => void,
  ownerScopeKey: string | null,
  requestClose?: ModalCloseRequest,
  { returnToResultsOnClose = true }: { returnToResultsOnClose?: boolean } = {},
) {
  const closeRef = useRef(onClose);
  const requestRef = useRef(requestClose);
  useLayoutEffect(() => { closeRef.current = onClose; requestRef.current = requestClose; }, [onClose, requestClose]);
  const entryRef = useRef<{ id: string; token: OwnerToken; owner: string | null } | null>(null);

  useEffect(() => {
    const entry = entryRef.current;
    const ownsTop = () => entry && window.history.state?.[MODAL_STATE] === entry.id;
    const strip = () => {
      if (!ownsTop()) return;
      const state = { ...window.history.state };
      delete state[MODAL_STATE];
      window.history.replaceState(state, '', window.location.href);
    };
    // Identity transitions revoke an overlay, never navigate somebody else's history.
    if (entry && (entry.owner !== ownerScopeKey || !isOwnerTokenValid(entry.token, entry.token.uid))) {
      strip();
      activeEntries.delete(entry.id);
      entryRef.current = null;
      closeRef.current();
      return;
    }
    if (open && !entry && window.location.pathname === '/results') {
      const token = captureOwnerToken();
      if (!isOwnerTokenValid(token, token.uid)) return;
      const id = crypto.randomUUID();
      try {
        window.history.pushState({ ...window.history.state, [MODAL_STATE]: id }, '', window.location.href);
        activeEntries.add(id);
        entryRef.current = { id, token, owner: ownerScopeKey };
      } catch { /* a browser that refuses history can still close with its button */ }
    } else if (!open && entry) {
      activeEntries.delete(entry.id);
      entryRef.current = null;
      if (ownsTop() && window.location.pathname === '/results') {
        // A host leaving Results (for example after its profile disappears)
        // owns that navigation. An asynchronous Back here would race its
        // router.replace and could restore the now-empty Results route.
        if (returnToResultsOnClose) window.history.back();
        else strip();
      }
    }
  }, [open, ownerScopeKey, returnToResultsOnClose]);

  useEffect(() => {
    const onPop = () => {
      const entry = entryRef.current;
      if (entry && window.history.state?.[MODAL_STATE] !== entry.id) {
        // Owner retirement always revokes private work. Never ask to keep it.
        const canGuard = isOwnerTokenValid(entry.token, entry.token.uid)
          && window.location.pathname === '/results';
        let closed = true;
        if (canGuard && requestRef.current) {
          try { closed = requestRef.current(); }
          catch { closed = false; } // an editor error must not discard its draft
        } else closeRef.current();
        if (!closed && isOwnerTokenValid(entry.token, entry.token.uid)) {
          // Back already consumed our entry. Reuse its identity on the current
          // result URL, preserving Next state, public filters and scroll. A
          // later explicit discard closes normally and consumes this one entry.
          try {
            window.history.pushState({ ...window.history.state, [MODAL_STATE]: entry.id }, '', window.location.href);
          } catch { /* keep the editor open even when history writes are denied */ }
          return;
        }
        if (!closed) closeRef.current(); // ownership changed during the request
        activeEntries.delete(entry.id);
        entryRef.current = null;
      } else if (!entry && window.history.state?.[MODAL_STATE]
        && !activeEntries.has(window.history.state[MODAL_STATE])) {
        // Forward may reach an old overlay entry after its draft was closed.
        // Do not invent/reopen a modal from navigation metadata.
        const state = { ...window.history.state };
        delete state[MODAL_STATE];
        window.history.replaceState(state, '', window.location.href);
      }
    };
    window.addEventListener('popstate', onPop);
    return () => {
      window.removeEventListener('popstate', onPop);
      const entry = entryRef.current;
      if (entry && window.history.state?.[MODAL_STATE] === entry.id) {
        const state = { ...window.history.state };
        delete state[MODAL_STATE];
        window.history.replaceState(state, '', window.location.href);
      }
      if (entry) activeEntries.delete(entry.id);
      entryRef.current = null;
    };
  }, []);
}
