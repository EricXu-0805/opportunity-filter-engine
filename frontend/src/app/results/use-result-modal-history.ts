'use client';

import { useEffect, useLayoutEffect, useRef } from 'react';
import { captureOwnerToken, isOwnerTokenValid, type OwnerToken } from '@/lib/identity-owner';

const MODAL_STATE = '__ofeResultsModal';
// Closed cards must not remove the history marker owned by another live card.
const activeEntries = new Set<string>();

/** Back closes a results overlay. It never changes the student's tracker. */
export function useResultModalHistory(open: boolean, onClose: () => void, ownerScopeKey: string | null) {
  const closeRef = useRef(onClose);
  useLayoutEffect(() => { closeRef.current = onClose; }, [onClose]);
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
      if (ownsTop() && window.location.pathname === '/results') window.history.back();
    }
  }, [open, ownerScopeKey]);

  useEffect(() => {
    const onPop = () => {
      const entry = entryRef.current;
      if (entry && window.history.state?.[MODAL_STATE] !== entry.id) {
        activeEntries.delete(entry.id);
        entryRef.current = null;
        closeRef.current();
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
