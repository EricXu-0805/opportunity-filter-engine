import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { OrdersSection } from './OrdersSection';
import type { OrdersInbox, TFunc } from './types';

const t: TFunc = (key) => key;

const okInbox = (overrides: Partial<OrdersInbox> = {}): OrdersInbox => ({
  status: 'ok',
  count: 2,
  orders: [
    {
      id: '11111111-2222-4333-8444-555555555555',
      device_id: 'dev-1',
      package: 'single_email',
      amount_cents: 990,
      currency: 'usd',
      status: 'awaiting_confirm',
      channel: 'manual',
      created_at: '2026-07-05T10:00:00+00:00',
      paid_at: null,
    },
    {
      id: '22222222-3333-4444-8555-666666666666',
      device_id: 'dev-2',
      package: 'full_package',
      amount_cents: 4900,
      currency: 'usd',
      status: 'paid',
      channel: 'manual',
      created_at: '2026-07-04T10:00:00+00:00',
      paid_at: '2026-07-04T12:00:00+00:00',
    },
  ],
  ...overrides,
});

describe('OrdersSection', () => {
  it('renders nothing before the inbox loads', () => {
    const { container } = render(<OrdersSection inbox={null} onConfirm={vi.fn()} t={t} />);
    expect(container.innerHTML).toBe('');
  });

  it('renders unconfigured as a quiet notice', () => {
    render(
      <OrdersSection
        inbox={{ status: 'skipped', reason: 'supabase env not configured' }}
        onConfirm={vi.fn()}
        t={t}
      />,
    );
    expect(screen.getByText('admin.orders.unconfigured')).toBeInTheDocument();
  });

  it('renders the empty state', () => {
    render(<OrdersSection inbox={okInbox({ orders: [], count: 0 })} onConfirm={vi.fn()} t={t} />);
    expect(screen.getByText('admin.orders.empty')).toBeInTheDocument();
  });

  it('lists orders and confirms an awaiting_confirm one', async () => {
    const onConfirm = vi.fn().mockResolvedValue(undefined);
    render(<OrdersSection inbox={okInbox()} onConfirm={onConfirm} t={t} />);
    expect(screen.getByText(/single_email/)).toBeInTheDocument();
    expect(screen.getByText(/\$9\.90/)).toBeInTheDocument();
    // paid order has no confirm button; only the awaiting one does
    const buttons = screen.getAllByText('admin.orders.confirm');
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    await waitFor(() =>
      expect(onConfirm).toHaveBeenCalledWith('11111111-2222-4333-8444-555555555555'),
    );
  });
});
