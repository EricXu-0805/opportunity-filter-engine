/** Browser-fixture receipt from the actual wire snapshot. No real email is sent. */
export interface ContactEventRequest {
  p_expected_device_id: string;
  p_event_id: string;
  p_opportunity_id: string;
  p_recipient: string;
  p_subject: string;
  p_body: string;
  p_materials: Array<{ kind: string; version: string }>;
  p_actual_sent_at: string | null;
}
export function contactEventReceiptForRequest(request: ContactEventRequest, options: {
  confirmedAt?: string;
  replayed?: boolean;
  interaction?: null | Record<string, unknown>;
} = {}) {
  const at = options.confirmedAt ?? new Date().toISOString();
  return {
    event: { event_id: request.p_event_id, device_id: request.p_expected_device_id, opportunity_id: request.p_opportunity_id,
      recipient: request.p_recipient, subject: request.p_subject, body: request.p_body, materials: request.p_materials,
      actual_sent_at: request.p_actual_sent_at, confirmed_at: at, confirmation_source: 'user_reported' },
    interaction: options.interaction === undefined ? {
      device_id: request.p_expected_device_id, opportunity_id: request.p_opportunity_id, interaction_type: 'contacted',
      notes: null, remind_at: null, last_contacted_at: at, updated_at: at,
    } : options.interaction,
    replayed: options.replayed ?? false,
  };
}
