'use client';

import dynamic from 'next/dynamic';
import { Sparkles } from 'lucide-react';
import type { Opportunity, ProfileData } from '@/lib/types';
import type { TFunc } from './types';

const OpportunityChatbot = dynamic(() => import('@/components/OpportunityChatbot'), { ssr: false });

export function ChatDrawer({
  opp,
  profile,
  open,
  onOpen,
  onClose,
  t,
}: {
  opp: Opportunity;
  profile: ProfileData | null;
  open: boolean;
  onOpen: () => void;
  onClose: () => void;
  t: TFunc;
}) {
  return (
    <>
      {!open && (
        <button
          type="button"
          onClick={onOpen}
          className="lg:hidden fixed bottom-6 right-6 z-30 inline-flex items-center justify-center w-14 h-14 rounded-full bg-indigo-600 text-white shadow-[0_4px_20px_rgba(79,70,229,0.4)] hover:bg-indigo-700 active:scale-95 transition-all"
          aria-label={t('chatbot.openAria')}
        >
          <Sparkles className="w-6 h-6" aria-hidden="true" />
        </button>
      )}

      {open && (
        <div className="lg:hidden fixed inset-0 z-50" role="dialog" aria-modal="true">
          <div
            className="absolute inset-0 bg-gray-900/50 backdrop-blur-sm"
            onClick={onClose}
            aria-hidden="true"
          />
          <div className="absolute bottom-0 left-0 right-0 bg-white rounded-t-2xl shadow-2xl flex flex-col max-h-[88vh] h-[88vh] animate-in">
            <OpportunityChatbot
              opportunity={opp}
              profile={profile}
              onClose={onClose}
            />
          </div>
        </div>
      )}
    </>
  );
}
