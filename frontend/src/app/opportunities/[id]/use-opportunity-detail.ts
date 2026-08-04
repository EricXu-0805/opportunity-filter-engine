'use client';

import { useCallback, useEffect, useState } from 'react';
import {
  getFavorites,
  toggleFavorite,
  trackInteraction,
  removeInteraction,
  getInteractionDetail,
  updateInteractionDetails,
} from '@/lib/supabase';
import type { InteractionType, InteractionRecord } from '@/lib/supabase';
import { track } from '@/lib/analytics';
import { suggestReminderForStatusChange, type ReminderSuggestion } from '@/lib/status-suggestions';
import { useAuthUid } from '@/lib/use-auth-uid';

export interface UseOpportunityDetailResult {
  isFavorited: boolean;
  interactionDetail: InteractionRecord | null;
  interaction: InteractionType | undefined;
  emailModalOpen: boolean;
  setEmailModalOpen: (v: boolean) => void;
  shareCopied: boolean;
  chatDrawerOpen: boolean;
  setChatDrawerOpen: (v: boolean) => void;
  suggestion: ReminderSuggestion | null;
  handleStar: () => Promise<void>;
  handleTrack: (type: InteractionType) => Promise<void>;
  /** W14: resolves true only when the write actually persisted — callers
   *  (TrackerPanel) gate their "Saved" flash on it. */
  saveDetails: (patch: { notes?: string | null; remind_at?: string | null }) => Promise<boolean>;
  handleUseSuggestion: () => Promise<void>;
  handleDismissSuggestion: () => void;
  handleShare: () => Promise<void>;
}

export function useOpportunityDetail(opp: { id: string; title: string }): UseOpportunityDetailResult {
  const [isFavorited, setIsFavorited] = useState(false);
  const [interactionDetail, setInteractionDetail] = useState<InteractionRecord | null>(null);
  const [emailModalOpen, setEmailModalOpen] = useState(false);
  const [shareCopied, setShareCopied] = useState(false);
  const [chatDrawerOpen, setChatDrawerOpen] = useState(false);
  const [suggestion, setSuggestion] = useState<ReminderSuggestion | null>(null);

  const interaction = interactionDetail?.type;

  // W14 cross-tab uid isolation: epoch bumps only on a real identity switch.
  const { epoch: authEpoch } = useAuthUid();

  // Analytics stays keyed on the opportunity only — an identity switch is
  // not a second "open".
  useEffect(() => {
    track('match_opened', { opportunity_id: opp.id });
  }, [opp.id]);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect --
       Reset before fetching — a no-op on mount, the isolation clear on an
       identity switch (Account A's star/status must not render for B). */
    setIsFavorited(false);
    setInteractionDetail(null);
    setSuggestion(null);
    /* eslint-enable react-hooks/set-state-in-effect */
    getFavorites().then((set) => {
      if (set.has(opp.id)) setIsFavorited(true);
    }).catch(() => {});
    getInteractionDetail(opp.id).then((d) => {
      if (d) setInteractionDetail(d);
    }).catch(() => {});
  }, [opp.id, authEpoch]);

  const handleStar = useCallback(async () => {
    const wasFav = isFavorited;
    setIsFavorited(!wasFav);
    try {
      await toggleFavorite(opp.id, wasFav);
    } catch {
      setIsFavorited(wasFav);
    }
  }, [opp.id, isFavorited]);

  const handleTrack = useCallback(async (type: InteractionType) => {
    const prev = interaction;
    const prevDetail = interactionDetail;
    if (prev === type) {
      setInteractionDetail(null);
      setSuggestion(null);
      await removeInteraction(opp.id).catch(() => {});
      return;
    }
    // Optimistic status only — no fabricated last_contacted_at: a manual
    // status pick is not a contact timestamp (the upsert never persisted it
    // anyway, so stamping it locally was dead-but-misleading state).
    setInteractionDetail((d) => ({
      ...(d ?? {}),
      type,
    }));
    try {
      await trackInteraction(opp.id, type);
    } catch {
      // W14: the write failed — revert the optimistic status instead of
      // displaying a state that was never persisted.
      setInteractionDetail(prevDetail);
      return;
    }

    if (!interactionDetail?.remind_at) {
      const next = suggestReminderForStatusChange(prev ?? null, type);
      if (next) setSuggestion(next);
    }
  }, [opp.id, interaction, interactionDetail]);

  const saveDetails = useCallback(
    async (patch: { notes?: string | null; remind_at?: string | null }): Promise<boolean> => {
      // Notes/reminders attach to an existing status the user chose. Never
      // fabricate an 'applied' here — that would record an outreach event
      // (a "send") the user did not report. The TrackerPanel disables
      // auto-save and shows a pick-a-status hint until one exists.
      if (!interaction) return false;
      setInteractionDetail((prev) => {
        const base: InteractionRecord = prev ?? { type: interaction };
        return {
          ...base,
          notes: patch.notes === null ? undefined : patch.notes ?? base.notes,
          remind_at: patch.remind_at === null ? undefined : patch.remind_at ?? base.remind_at,
        };
      });
      // W14: propagate the write result — TrackerPanel shows "Saved" only on
      // true and a failed-save + retry state on false.
      return updateInteractionDetails(opp.id, patch);
    },
    [opp.id, interaction],
  );

  const handleUseSuggestion = useCallback(async () => {
    if (!suggestion) return;
    const date = suggestion.date;
    setSuggestion(null);
    await saveDetails({ remind_at: date });
  }, [suggestion, saveDetails]);

  const handleDismissSuggestion = useCallback(() => setSuggestion(null), []);

  const handleShare = useCallback(async () => {
    const url = typeof window !== 'undefined' ? window.location.href : '';
    try {
      if (navigator.share) {
        await navigator.share({ title: opp.title, url });
      } else {
        await navigator.clipboard.writeText(url);
        setShareCopied(true);
        setTimeout(() => setShareCopied(false), 2000);
      }
    } catch {
      /* user canceled */
    }
  }, [opp.title]);

  return {
    isFavorited,
    interactionDetail,
    interaction,
    emailModalOpen,
    setEmailModalOpen,
    shareCopied,
    chatDrawerOpen,
    setChatDrawerOpen,
    suggestion,
    handleStar,
    handleTrack,
    saveDetails,
    handleUseSuggestion,
    handleDismissSuggestion,
    handleShare,
  };
}
