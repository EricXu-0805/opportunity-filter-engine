'use client';

import { useState } from 'react';
import { CreditCard } from 'lucide-react';
import type { OrdersInbox, TFunc } from './types';

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-gray-100 text-gray-600',
  awaiting_confirm: 'bg-amber-50 text-amber-700',
  paid: 'bg-emerald-50 text-emerald-700',
  cancelled: 'bg-gray-100 text-gray-400',
  refunded: 'bg-red-50 text-red-600',
};

export function OrdersSection({
  inbox,
  onConfirm,
  t,
}: {
  inbox: OrdersInbox | null;
  onConfirm: (id: string) => Promise<void>;
  t: TFunc;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  if (!inbox) return null;
  const orders = inbox.orders ?? [];
  return (
    <section className="mt-10">
      <h2 className="text-[15px] font-semibold text-gray-900 mb-3 flex items-center gap-2">
        <CreditCard className="w-4 h-4 text-indigo-600" />
        {t('admin.orders.title')}
      </h2>
      {inbox.status !== 'ok' ? (
        <p className="text-[13px] text-gray-400 italic">{t('admin.orders.unconfigured')}</p>
      ) : (
        <div>
          <p className="text-[12px] font-medium text-gray-500 mb-2">
            {t('admin.orders.inbox', { count: orders.length })}
          </p>
          {orders.length === 0 ? (
            <p className="text-[13px] text-gray-400 italic">{t('admin.orders.empty')}</p>
          ) : (
            <ul className="space-y-2">
              {orders.map((o) => (
                <li key={o.id} className="rounded-xl border border-black/[0.06] bg-white px-3.5 py-2.5">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-gray-400">
                    <span>{new Date(o.created_at).toLocaleString()}</span>
                    <span className="font-mono">{o.id.slice(0, 8)}</span>
                    <span className={`px-2 py-0.5 rounded-full font-medium ${STATUS_STYLES[o.status] ?? 'bg-gray-100 text-gray-600'}`}>
                      {o.status}
                    </span>
                  </div>
                  <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[13px] text-gray-800">
                      {o.package} · ${(o.amount_cents / 100).toFixed(2)} {o.currency.toUpperCase()} · {o.channel}
                      {o.status === 'paid' && o.paid_at && (
                        <span className="text-gray-400"> · {t('admin.orders.paidAt', { when: new Date(o.paid_at).toLocaleString() })}</span>
                      )}
                    </p>
                    {(o.status === 'awaiting_confirm' || o.status === 'pending') && (
                      <button
                        type="button"
                        disabled={confirming === o.id}
                        onClick={async () => {
                          setConfirming(o.id);
                          try { await onConfirm(o.id); } finally { setConfirming(null); }
                        }}
                        className="px-3 py-1.5 rounded-lg text-[12px] font-medium text-white bg-indigo-600 hover:bg-indigo-700 disabled:opacity-60"
                      >
                        {confirming === o.id ? t('admin.orders.confirming') : t('admin.orders.confirm')}
                      </button>
                    )}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
