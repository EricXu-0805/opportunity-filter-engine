'use client';

import { useEffect, useRef } from 'react';
import { X } from 'lucide-react';

type Translate = (path: string, vars?: Record<string, string | number>) => string;

export function KeyboardHelpDialog({
  onClose,
  t,
}: {
  onClose: () => void;
  t: Translate;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    }
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [onClose]);

  const shortcuts: Array<[string, string]> = [
    ['/', t('results.keyboardHelp.focusSearch')],
    ['j  or  \u2193', t('results.keyboardHelp.next')],
    ['k  or  \u2191', t('results.keyboardHelp.prev')],
    ['s', t('results.keyboardHelp.star')],
    ['Enter', t('results.keyboardHelp.open')],
    ['Esc', t('results.keyboardHelp.closeDialog')],
    ['?', t('results.keyboardHelp.showHelp')],
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="kbd-help-title"
    >
      <div className="absolute inset-0 bg-gray-900/60 backdrop-blur-sm" onClick={onClose} aria-hidden="true" />
      <div className="relative w-full max-w-md bg-white rounded-2xl shadow-2xl overflow-hidden animate-in">
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 id="kbd-help-title" className="text-[15px] font-semibold text-gray-900">{t('results.keyboardHelp.title')}</h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            className="p-2 -mr-2 rounded-lg hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            aria-label={t('results.keyboardHelp.closeAria')}
          >
            <X className="w-4 h-4 text-gray-400" aria-hidden="true" />
          </button>
        </div>
        <dl className="divide-y divide-gray-50">
          {shortcuts.map(([keys, desc]) => (
            <div key={keys} className="flex items-center justify-between px-6 py-3">
              <dt className="text-[13px] text-gray-600">{desc}</dt>
              <dd>
                <kbd className="inline-flex items-center justify-center h-6 px-2 text-[11px] font-mono font-medium text-gray-700 bg-gray-100 border border-gray-200 rounded">
                  {keys}
                </kbd>
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
