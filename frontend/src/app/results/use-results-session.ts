'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import type { MatchViewRequestState } from '@/lib/api';
import type { ProfileData } from '@/lib/types';
import { captureOwnerToken, isOwnerTokenValid, type OwnerToken } from '@/lib/identity-owner';
import {
  discardResultSession, readResultSession, resultRequestKey, sessionBelongsToOwner,
  writeResultSession, type ResultCursorState, type ResultSession,
} from '@/lib/result-session';

interface Props {
  arrivalId: string | null;
  profile: ProfileData | null;
  semantic: boolean;
  view: MatchViewRequestState;
  ready: boolean;
  failed: boolean;
  publicUrl: string;
  page: number;
  setPage: (page: number) => void;
  setShowDismissed: (show: boolean) => void;
}

/** A same-tab return ticket. It can seed cursors, never data or scores. */
export function useResultsSession(props: Props) {
  const { arrivalId, profile, semantic, view, ready, failed, publicUrl, page, setPage, setShowDismissed } = props;
  const [settled, setSettled] = useState(!arrivalId);
  const [sessionId, setSessionId] = useState<string | null>(arrivalId);
  const [restore, setRestore] = useState<ResultSession | null>(null);
  const [resetNotice, setResetNotice] = useState(false);
  const [viewedIds, setViewedIds] = useState<Set<string>>(new Set());
  const sessionRef = useRef<ResultSession | null>(null);
  const validatedRef = useRef<ResultCursorState | null>(null);
  const validatedOwnerRef = useRef<OwnerToken | null>(null);
  const viewedRef = useRef<string[]>([]);
  const positionRef = useRef<ResultSession | null>(null);
  const requestKey = profile ? resultRequestKey(profile, semantic, view) : '';
  // A delayed animation frame must still belong to this exact request/page.
  const currentRef = useRef({ requestKey, page, ready });
  useLayoutEffect(() => { currentRef.current = { requestKey, page, ready }; }, [requestKey, page, ready]);

  /* eslint-disable react-hooks/set-state-in-effect -- accept a bounded external session only after owner/profile hydration succeeds */
  useEffect(() => {
    if (settled || (!ready && !failed) || !profile) return;
    const saved = ready ? readResultSession(arrivalId) : null;
    const expectedKey = saved
      ? resultRequestKey(profile, semantic, { ...view, show_dismissed: saved.showDismissed })
      : '';
    if (saved && saved.requestKey === expectedKey) {
      sessionRef.current = saved;
      positionRef.current = saved;
      setRestore(saved);
      setPage(saved.page);
      setShowDismissed(saved.showDismissed);
      viewedRef.current = saved.viewedIds;
      setViewedIds(new Set(saved.viewedIds));
    } else {
      setSessionId(null);
      setPage(1);
      setResetNotice(true);
    }
    setSettled(true);
  }, [arrivalId, failed, profile, ready, semantic, setPage, setShowDismissed, settled, view]);
  /* eslint-enable react-hooks/set-state-in-effect */

  const resetForIdentity = useCallback(() => {
    const old = sessionRef.current;
    if (old) discardResultSession(old.id);
    sessionRef.current = null;
    validatedRef.current = null;
    validatedOwnerRef.current = null;
    viewedRef.current = [];
    positionRef.current = null;
    setRestore(null);
    setSessionId(null);
    setViewedIds(new Set());
    setResetNotice(false);
    setSettled(true);
  }, []);

  const cursorExpired = useCallback(() => {
    positionRef.current = null;
    validatedRef.current = null;
    setRestore(null);
    setPage(1);
    setResetNotice(true);
  }, [setPage]);

  const onValidated = useCallback((state: ResultCursorState, origin?: OwnerToken) => {
    if (state.requestKey !== requestKey || state.page !== page) return;
    const token = origin ?? captureOwnerToken();
    if (!isOwnerTokenValid(token, token.uid)) return;
    validatedRef.current = state;
    validatedOwnerRef.current = token;
    if (!ready) return;
    if (!isOwnerTokenValid(token, token.uid)) return;
    const previous = sessionRef.current;
    const sameVisit = previous && sessionBelongsToOwner(previous, token) && previous.requestKey === state.requestKey;
    const samePage = sameVisit && previous.page === state.page;
    const saved = writeResultSession({
      ...state,
      ...(sameVisit ? { id: previous.id } : {}),
      returnUrl: publicUrl,
      showDismissed: view.show_dismissed,
      anchorId: samePage ? previous.anchorId : null,
      anchorOffset: samePage ? previous.anchorOffset : null,
      scrollY: samePage ? previous.scrollY : window.scrollY,
      viewedIds: viewedRef.current,
    }, token);
    sessionRef.current = saved;
    setSessionId(saved?.id ?? null);
    const position = positionRef.current;
    if (!position || position.requestKey !== state.requestKey || position.page !== state.page) return;
    // Wait for the validated cards to commit, not for a stored snapshot to paint.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      const current = currentRef.current;
      if (window.location.pathname !== '/results' || positionRef.current !== position || !isOwnerTokenValid(token, token.uid)
        || !current.ready || current.requestKey !== state.requestKey || current.page !== state.page) return;
      positionRef.current = null;
      const anchor = position.anchorId ? document.getElementById(`match-card-${position.anchorId}`) : null;
      const top = anchor && position.anchorOffset !== null
        ? window.scrollY + anchor.getBoundingClientRect().top - position.anchorOffset
        : position.scrollY;
      window.scrollTo({ top: Math.max(0, top), behavior: 'instant' });
    }));
  }, [page, publicUrl, ready, requestKey, view.show_dismissed]);

  useEffect(() => {
    const validated = validatedRef.current;
    const token = validatedOwnerRef.current;
    if (ready && validated && token && isOwnerTokenValid(token, token.uid)) onValidated(validated, token);
  }, [ready, onValidated]);

  const rememberOpportunity = useCallback((id: string) => {
    const token = captureOwnerToken();
    const saved = sessionRef.current;
    const state = validatedRef.current;
    const validatedOwner = validatedOwnerRef.current;
    if (!ready || !state || state.requestKey !== requestKey || state.page !== page
      || !validatedOwner || !isOwnerTokenValid(validatedOwner, validatedOwner.uid)
      || (saved && !sessionBelongsToOwner(saved, token))) return;
    const viewed = [...new Set([...viewedRef.current, id])].slice(-512);
    viewedRef.current = viewed;
    setViewedIds(new Set(viewed));
    // A refused sessionStorage write disables return tickets, not this visible mark.
    if (!saved) return;
    const anchor = document.getElementById(`match-card-${id}`);
    const next = writeResultSession({
      ...saved, viewedIds: viewed, anchorId: id,
      anchorOffset: anchor?.getBoundingClientRect().top ?? null, scrollY: window.scrollY,
    }, token);
    sessionRef.current = next;
    if (!next) setSessionId(null);
  }, [page, ready, requestKey]);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const flushScroll = () => {
      clearTimeout(timer);
      const saved = sessionRef.current;
      const current = currentRef.current;
      if (window.location.pathname !== '/results' || !saved || positionRef.current || !current.ready || saved.requestKey !== current.requestKey || saved.page !== current.page) return;
      const token = captureOwnerToken();
      if (!sessionBelongsToOwner(saved, token)) return;
      const anchor = saved.anchorId ? document.getElementById(`match-card-${saved.anchorId}`) : null;
      // Navigation may already have removed the old list before cleanup runs.
      if (saved.anchorId && !anchor) return;
      // Refresh need not follow an opportunity click. Capture the visible
      // list position as an anchor too, without marking any row as viewed.
      // Prefer a card whose top is on screen so its heading remains useful
      // even if rows above it have a different height after hydration.
      const cards = Array.from(document.querySelectorAll<HTMLElement>('[id^="match-card-"]'));
      const visible = cards.find((card) => {
        const rect = card.getBoundingClientRect();
        return rect.height > 0 && rect.top >= 0 && rect.top < window.innerHeight;
      }) ?? cards.find((card) => {
        const rect = card.getBoundingClientRect();
        return rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight;
      }) ?? anchor;
      const next = writeResultSession({ ...saved, scrollY: window.scrollY,
        anchorId: visible ? visible.id.slice('match-card-'.length) : null,
        anchorOffset: visible?.getBoundingClientRect().top ?? null }, token);
      sessionRef.current = next;
    };
    const saveScroll = () => {
      clearTimeout(timer);
      timer = setTimeout(flushScroll, 150);
    };
    // A student who starts interacting owns their position; a late request
    // must not drag them back to an earlier visit's anchor.
    const cancelPosition = () => { positionRef.current = null; };
    window.addEventListener('scroll', saveScroll, { passive: true });
    window.addEventListener('pagehide', flushScroll);
    window.addEventListener('wheel', cancelPosition, { passive: true });
    window.addEventListener('touchstart', cancelPosition, { passive: true });
    window.addEventListener('pointerdown', cancelPosition);
    window.addEventListener('keydown', cancelPosition);
    return () => {
      flushScroll();
      positionRef.current = null;
      window.removeEventListener('pagehide', flushScroll);
      window.removeEventListener('scroll', saveScroll);
      window.removeEventListener('wheel', cancelPosition);
      window.removeEventListener('touchstart', cancelPosition);
      window.removeEventListener('pointerdown', cancelPosition);
      window.removeEventListener('keydown', cancelPosition);
    };
  }, []);

  return { settled, sessionId, restore, resetNotice, viewedIds, resetForIdentity, cursorExpired, onValidated, rememberOpportunity };
}
