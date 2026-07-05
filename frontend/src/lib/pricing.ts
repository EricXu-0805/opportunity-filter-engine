// Concierge package pricing — placeholder anchors Eric revises before launch.
// The order flow is gated by NEXT_PUBLIC_PAYMENTS; unset keeps the account
// page on the waitlist-only behavior.

export interface PricingPackage {
  id: 'single_email' | 'full_package';
  amountCents: number;
  currency: 'usd';
}

export type PackageId = PricingPackage['id'];

export const PACKAGES: readonly PricingPackage[] = [
  { id: 'single_email', amountCents: 990, currency: 'usd' },
  { id: 'full_package', amountCents: 4900, currency: 'usd' },
];

export function packageById(id: string): PricingPackage | undefined {
  return PACKAGES.find((p) => p.id === id);
}

export function formatPrice(amountCents: number): string {
  return `$${(amountCents / 100).toFixed(2)}`;
}

export function paymentsEnabled(): boolean {
  const v = process.env.NEXT_PUBLIC_PAYMENTS;
  return v === 'true' || v === '1';
}
