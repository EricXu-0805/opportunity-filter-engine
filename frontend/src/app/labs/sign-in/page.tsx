'use client';

/*
 * Labs prototype — sign-in redesign, MODAL presentation (chosen direction).
 *
 * Direct-URL only (/labs/sign-in); intentionally NOT linked from any nav.
 * Eric's review decision (2026-06): the centered card won over the
 * split-panel page, presented as a modal over the current page rather
 * than a separate route. This page demos exactly that: a non-interactive
 * results-page skeleton stands in for "the current page" (the real
 * Header above comes from the root layout), and SignInModal opens over
 * it. Close it (X / Esc / backdrop) and the labs bar offers 重新打开弹窗.
 *
 * Production path: SignInModal's design upgrades the existing AuthModal
 * signin phase; /auth/sign-in stays only as a deep-link fallback that
 * opens the same modal.
 */

import { FlaskConical } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';
import SignInModal from './SignInModal';

/** Cheap stand-in for the results page: just enough gray boxes to read
 *  as "the app behind the modal". Non-interactive by construction. */
function MockResultsBackdrop() {
  return (
    <div aria-hidden="true" className="pointer-events-none select-none">
      <div className="bg-white rounded-2xl shadow-[0_2px_12px_rgba(0,0,0,0.06)] p-4 mb-6">
        <div className="h-10 rounded-xl bg-gray-100" />
        <div className="flex gap-2 mt-3">
          <div className="h-6 w-20 rounded-full bg-gray-100" />
          <div className="h-6 w-28 rounded-full bg-gray-100" />
          <div className="h-6 w-16 rounded-full bg-gray-100" />
          <div className="h-6 w-24 rounded-full bg-gray-100" />
        </div>
      </div>
      <div className="grid sm:grid-cols-2 gap-4">
        {[0, 1, 2, 3].map(i => (
          <div
            key={i}
            className="bg-white rounded-3xl shadow-[0_2px_12px_rgba(0,0,0,0.06)] p-6"
          >
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-gray-100 shrink-0" />
              <div className="flex-1 space-y-2">
                <div className="h-3.5 w-3/4 rounded bg-gray-100" />
                <div className="h-3 w-1/2 rounded bg-gray-100" />
              </div>
            </div>
            <div className="mt-4 space-y-2">
              <div className="h-3 rounded bg-gray-100" />
              <div className="h-3 w-5/6 rounded bg-gray-100" />
            </div>
            <div className="mt-4 flex gap-2">
              <div className="h-6 w-16 rounded-full bg-gray-100" />
              <div className="h-6 w-20 rounded-full bg-gray-100" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function SignInLabsPage() {
  const [open, setOpen] = useState(true);

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-14 page-enter">
      <div className="mb-10 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
        <p className="flex items-start sm:items-center gap-2 text-[12px] text-amber-900 leading-relaxed">
          <FlaskConical className="w-4 h-4 text-amber-700 shrink-0 mt-0.5 sm:mt-0" aria-hidden="true" />
          <span>
            Labs preview — sign-in modal redesign (chosen direction). Visual prototype only;
            nothing is wired. 设计稿预览，未接通后端。
          </span>
        </p>
        {!open && (
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="px-3.5 py-1.5 rounded-full bg-gray-900 text-white text-[12px] font-medium hover:bg-black transition-colors self-start sm:self-auto shrink-0"
          >
            重新打开弹窗 · Reopen modal
          </button>
        )}
      </div>

      <MockResultsBackdrop />

      <p className="mt-16 text-center text-[12px] text-gray-400">
        Compare with the live flow:{' '}
        <Link href="/auth/sign-in" className="underline hover:text-gray-600">
          /auth/sign-in
        </Link>{' '}
        (opens the current AuthModal) · 现有登录入口对比
      </p>

      {/* Mounted conditionally (SaveSearchDialog pattern) so each open
          starts from fresh state. */}
      {open && <SignInModal onClose={() => setOpen(false)} />}
    </div>
  );
}
