'use client';

/*
 * Labs prototype — sign-in page redesign.
 *
 * Direct-URL only (/labs/sign-in); intentionally NOT linked from any
 * nav. Two visual variants, toggleable from the labs bar:
 *   - split:    promo panel (headline + value props) left, auth card right
 *   - centered: single max-w-md column, compact value-prop strip below
 *
 * Everything is mocked. The production version replaces the deep-link
 * stub at /auth/sign-in; the AuthModal stays for in-flow prompts.
 */

import { FlaskConical } from 'lucide-react';
import Link from 'next/link';
import { useState } from 'react';
import AuthCard from './AuthCard';
import { Headline, ValuePropList, ValuePropsRow } from './ValueProps';

type Variant = 'split' | 'centered';

const VARIANTS: { id: Variant; label: string }[] = [
  { id: 'split', label: 'Split panel' },
  { id: 'centered', label: 'Centered' },
];

export default function SignInLabsPage() {
  const [variant, setVariant] = useState<Variant>('split');

  return (
    <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-10 sm:py-14 page-enter">
      <div className="mb-10 flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3">
        <p className="flex items-start sm:items-center gap-2 text-[12px] text-amber-900 leading-relaxed">
          <FlaskConical className="w-4 h-4 text-amber-700 shrink-0 mt-0.5 sm:mt-0" aria-hidden="true" />
          <span>
            Labs preview — sign-in page redesign. Visual prototype only; nothing is wired.
            设计稿预览，未接通后端。
          </span>
        </p>
        <div
          className="flex items-center gap-0.5 self-start sm:self-auto shrink-0 bg-white/80 border border-amber-200 rounded-full p-0.5"
          role="group"
          aria-label="Layout variant"
        >
          {VARIANTS.map(v => (
            <button
              key={v.id}
              type="button"
              onClick={() => setVariant(v.id)}
              aria-pressed={variant === v.id}
              className={`px-3 py-1 rounded-full text-[12px] font-medium transition-colors ${
                variant === v.id
                  ? 'bg-black/[0.06] text-gray-900'
                  : 'text-gray-500 hover:text-gray-900'
              }`}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      {variant === 'split' ? (
        <div className="grid gap-10 lg:grid-cols-2 lg:gap-16 items-start">
          <div className="lg:col-start-1 lg:row-start-1">
            <Headline />
          </div>
          <div className="lg:col-start-2 lg:row-start-1 lg:row-span-2 max-w-md w-full mx-auto lg:mx-0 lg:justify-self-end">
            <AuthCard />
          </div>
          <div className="lg:col-start-1 lg:row-start-2">
            <ValuePropList />
          </div>
        </div>
      ) : (
        <div className="max-w-md mx-auto">
          <Headline centered />
          <div className="mt-8">
            <AuthCard />
          </div>
          <div className="mt-10">
            <ValuePropsRow />
          </div>
        </div>
      )}

      <p className="mt-16 text-center text-[12px] text-gray-400">
        Compare with the live flow:{' '}
        <Link href="/auth/sign-in" className="underline hover:text-gray-600">
          /auth/sign-in
        </Link>{' '}
        (opens the current AuthModal) · 现有登录入口对比
      </p>
    </div>
  );
}
