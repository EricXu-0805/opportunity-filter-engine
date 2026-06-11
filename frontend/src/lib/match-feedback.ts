import { getDeviceId, supabase } from './supabase';

// Phase 9.6 minimal feedback loop: one thumbs up/down verdict per user per
// opportunity, stored server-side via the same device_id = auth.uid()::text
// model as favorites / saved_searches (see 012_match_feedback.sql).
//
// Every helper degrades to an empty / no-op result when the table doesn't
// exist yet — the migration may lag the deploy, and feedback is strictly
// additive, so a missing table must never break the results page.

export type MatchVerdict = 'up' | 'down';

export interface MatchFeedbackContext {
  bucket: string;
  finalScore: number;
}

function isMissingTable(message: string | undefined): boolean {
  return Boolean(message?.toLowerCase().includes('does not exist'));
}

export async function getMatchFeedback(ids: string[]): Promise<Map<string, MatchVerdict>> {
  if (ids.length === 0) return new Map();
  const deviceId = await getDeviceId();
  if (!deviceId) return new Map();

  const { data, error } = await supabase
    .from('match_feedback')
    .select('opportunity_id, verdict')
    .eq('device_id', deviceId)
    .in('opportunity_id', ids);

  if (error || !data) {
    if (error && !isMissingTable(error.message)) {
      console.warn('[ofe] getMatchFeedback failed:', error.message);
    }
    return new Map();
  }

  return new Map(
    data.map((r: { opportunity_id: string; verdict: MatchVerdict }) => [
      r.opportunity_id,
      r.verdict,
    ]),
  );
}

export async function setMatchFeedback(
  opportunityId: string,
  verdict: MatchVerdict | null,
  context: MatchFeedbackContext,
): Promise<boolean> {
  const deviceId = await getDeviceId();
  if (!deviceId) return false;

  if (verdict === null) {
    const { error } = await supabase
      .from('match_feedback')
      .delete()
      .eq('device_id', deviceId)
      .eq('opportunity_id', opportunityId);

    if (error) {
      if (!isMissingTable(error.message)) {
        console.warn('[ofe] setMatchFeedback clear failed:', error.message);
      }
      return false;
    }
    return true;
  }

  // created_at is refreshed on re-vote so the row always records when the
  // *current* verdict was given — the old verdict is overwritten anyway.
  const { error } = await supabase
    .from('match_feedback')
    .upsert(
      {
        device_id: deviceId,
        opportunity_id: opportunityId,
        verdict,
        bucket: context.bucket,
        final_score: context.finalScore,
        created_at: new Date().toISOString(),
      },
      { onConflict: 'device_id,opportunity_id' },
    );

  if (error) {
    if (!isMissingTable(error.message)) {
      console.warn('[ofe] setMatchFeedback failed:', error.message);
    }
    return false;
  }
  return true;
}
