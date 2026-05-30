'use client';

import Link from 'next/link';
import { AlertTriangle, ArrowLeft, Database } from 'lucide-react';
import type { TFunc } from './types';

export function AdminLoginForm({
  tokenInput,
  setTokenInput,
  onSubmit,
  loading,
  error,
  t,
}: {
  tokenInput: string;
  setTokenInput: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  loading: boolean;
  error: string | null;
  t: TFunc;
}) {
  return (
    <div className="min-h-screen bg-gradient-to-b from-white to-gray-50">
      <div className="max-w-2xl mx-auto px-4 sm:px-6 lg:px-8 py-10">
        <Link href="/" className="inline-flex items-center gap-2 text-sm text-gray-500 hover:text-gray-900 mb-6">
          <ArrowLeft className="w-4 h-4" />
          {t('admin.back')}
        </Link>
        <div className="mb-8">
          <h1 className="text-3xl font-bold text-gray-900 tracking-tight flex items-center gap-3">
            <Database className="w-7 h-7 text-blue-600" />
            {t('admin.title')}
          </h1>
          <p className="mt-2 text-[14px] text-gray-500">{t('admin.subtitle')}</p>
        </div>
        {error && (
          <div className="flex items-start gap-3 bg-red-50 border border-red-200 rounded-xl p-4 mb-6">
            <AlertTriangle className="w-4 h-4 text-red-600 mt-0.5 shrink-0" />
            <p className="text-sm text-red-800">{error}</p>
          </div>
        )}
        <div className="bg-white rounded-2xl shadow-sm border border-gray-100 p-6">
          <p className="text-[14px] text-gray-600 mb-4">{t('admin.unauthorizedHint')}</p>
          <form onSubmit={onSubmit} className="flex gap-2">
            <input
              type="password"
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Admin token"
              className="flex-1 px-3.5 py-2 border border-gray-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 outline-none"
              autoFocus
              autoComplete="off"
            />
            <button type="submit" disabled={!tokenInput || loading} className="px-4 py-2 rounded-xl bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 disabled:opacity-50">
              {loading ? '...' : 'Load'}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
