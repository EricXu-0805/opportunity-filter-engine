-- 025_confirm_interaction_contact.sql
-- Atomic replacement for the client's read (getInteractionDetail) ->
-- conditional upsert (trackInteraction 'applied') -> metadata update
-- (updateInteractionDetails) Cold Email confirm flow, which is TOCTOU: two
-- concurrent confirms (or a confirm racing a manual status change) can
-- interleave their reads and writes and silently downgrade an advanced
-- status (replied/interviewing/rejected/dismissed) back to 'applied', or
-- double-fire the interaction_status_changes trigger (009). One INSERT ...
-- ON CONFLICT DO UPDATE closes that window: it either creates the row as
-- 'contacted' (the honest state for a sent outreach email — see 024) or,
-- if a status already exists, ONLY refreshes
-- last_contacted_at (+ an explicitly supplied remind_at) — it can never
-- touch interaction_type or notes, so an existing further-along status and
-- any notes survive byte-for-byte.
--
-- SECURITY INVOKER (not DEFINER): this function needs no elevated
-- privilege over the caller's own RLS-scoped access to `interactions` — it
-- just closes the read/write race, so it runs as the calling role and
-- stays subject to the existing interactions_insert_own/
-- interactions_update_own policies (device_id = auth.uid()::text, see
-- 006_anonymous_auth_rls.sql) as a second, independent enforcement layer
-- behind the explicit owner check below.

CREATE OR REPLACE FUNCTION public.confirm_interaction_contact(
  p_expected_device_id text,
  p_opportunity_id text,
  p_remind_at date DEFAULT NULL
)
RETURNS SETOF interactions
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
BEGIN
  -- The caller captures p_expected_device_id at the moment of the user's
  -- click, before any await — if the session identity has since changed
  -- (sign-out, account switch), auth.uid() no longer matches what the
  -- click was attributed to, and the write must fail closed rather than
  -- land on whichever identity happens to be current now. p_expected_
  -- device_id IS NULL is checked explicitly first: IS DISTINCT FROM treats
  -- two NULLs as NOT distinct, so an unauthenticated caller (auth.uid()
  -- NULL) passing a null device id would otherwise slip past the guard
  -- and hit the NOT NULL constraint on interactions.device_id instead of
  -- this intentional, stably-named rejection.
  IF p_expected_device_id IS NULL
     OR auth.uid()::text IS DISTINCT FROM p_expected_device_id THEN
    RAISE EXCEPTION 'identity_changed' USING ERRCODE = '42501';
  END IF;
  IF p_opportunity_id IS NULL OR btrim(p_opportunity_id) = '' THEN
    RAISE EXCEPTION 'invalid_opportunity' USING ERRCODE = '22023';
  END IF;

  RETURN QUERY
  INSERT INTO interactions (device_id, opportunity_id, interaction_type, last_contacted_at, remind_at, updated_at)
  -- 'contacted', not 'applied' (W12's 024): a confirmed cold-email send is
  -- an outreach contact, never an application claim made on the user's behalf.
  VALUES (p_expected_device_id, p_opportunity_id, 'contacted', now(), p_remind_at, now())
  ON CONFLICT (device_id, opportunity_id) DO UPDATE SET
    last_contacted_at = EXCLUDED.last_contacted_at,
    remind_at = COALESCE(EXCLUDED.remind_at, interactions.remind_at),
    updated_at = EXCLUDED.updated_at
  RETURNING *;
END;
$$;

REVOKE ALL ON FUNCTION public.confirm_interaction_contact(text, text, date) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.confirm_interaction_contact(text, text, date) TO authenticated;
