import { supabase, getDeviceId } from './supabase';

export type FunnelEvent =
  | 'landing_view'
  | 'matches_generated'
  | 'match_opened'
  | 'ai_feature_used'
  | 'intent_clicked'
  | 'concierge_cta_view'
  | 'concierge_request_submitted'
  | 'pay_qr_view'
  | 'order_created'
  | 'feedback_submitted'
  | 'onboarding_completed'
  | 'school_confirmed';

// Fire-and-forget funnel instrumentation. NEVER throws and NEVER blocks the UI:
// a failed insert (offline, no session, RLS) is swallowed — analytics must not
// degrade the product. Rows go straight to Supabase under the same per-user RLS
// as favorites/interactions (device_id = auth.uid()); the client cannot read
// them back (the operator aggregates with the service-role key). See
// supabase/migrations/015_analytics_waitlist.sql.
export async function track(
  event: FunnelEvent,
  props: Record<string, unknown> = {},
): Promise<void> {
  try {
    const deviceId = await getDeviceId();
    if (!deviceId) return;
    await supabase.from('analytics_events').insert({ device_id: deviceId, event, props });
  } catch {
    /* best-effort: analytics must never surface an error to the user */
  }
}

// Like track(), but fires a given event at most once per browser tab session —
// for the page-view-style steps (landing, first matches) that would otherwise
// re-fire on every re-render/navigation and inflate the funnel counts.
export async function trackOnce(
  event: FunnelEvent,
  props: Record<string, unknown> = {},
): Promise<void> {
  const key = `ofe_tracked_${event}`;
  try {
    if (typeof window !== 'undefined') {
      if (window.sessionStorage.getItem(key)) return;
      window.sessionStorage.setItem(key, '1');
    }
  } catch {
    /* sessionStorage unavailable (private mode/SSR) — fall through and track */
  }
  await track(event, props);
}
