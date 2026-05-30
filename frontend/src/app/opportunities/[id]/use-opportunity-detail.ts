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
import { suggestReminderForStatusChange, type ReminderSuggestion } from '@/lib/status-suggestions';

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
  saveDetails: (patch: { notes?: string | null; remind_at?: string | null }) => Promise<void>;
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

  useEffect(() => {
    getFavorites().then((set) => {
      if (set.has(opp.id)) setIsFavorited(true);
    }).catch(() => {});
    getInteractionDetail(opp.id).then((d) => {
      if (d) setInteractionDetail(d);
    }).catch(() => {});
  }, [opp.id]);

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
    if (prev === type) {
      setInteractionDetail(null);
      setSuggestion(null);
      await removeInteraction(opp.id).catch(() => {});
      return;
    }
    setInteractionDetail((d) => ({
      ...(d ?? {}),
      type,
      last_contacted_at: new Date().toISOString(),
    }));
    await trackInteraction(opp.id, type).catch(() => {});

    if (!interactionDetail?.remind_at) {
      const next = suggestReminderForStatusChange(prev ?? null, type);
      if (next) setSuggestion(next);
    }
  }, [opp.id, interaction, interactionDetail?.remind_at]);

  const saveDetails = useCallback(
    async (patch: { notes?: string | null; remind_at?: string | null }) => {
      if (!interaction) {
        await trackInteraction(opp.id, 'applied').catch(() => {});
      }
      setInteractionDetail((prev) => {
        const base: InteractionRecord = prev ?? { type: 'applied' };
        return {
          ...base,
          notes: patch.notes === null ? undefined : patch.notes ?? base.notes,
          remind_at: patch.remind_at === null ? undefined : patch.remind_at ?? base.remind_at,
        };
      });
      await updateInteractionDetails(opp.id, patch).catch(() => {});
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
