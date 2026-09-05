-- 034: a merge that keeps what it moves.
--
-- Flow B hands a guest's work to the account they sign in as. Three ways it
-- did not.
--
-- 1. It aborted, and could never stop aborting. 033 added
--    waitlist_one_request_per_target UNIQUE (device_id, opportunity_id) WHERE
--    opportunity_id IS NOT NULL. The merge still deduped waitlist on
--    (email, intent) and then re-keyed the survivors, so two accounts holding a
--    concierge request for the SAME professor under different emails raised
--    23505. That rolls back the WHOLE call — every table — and the grant is
--    consumed last, so it is never consumed. The message is not in
--    DEFINITIVE_GRANT_ERRORS, so /auth/callback shows its retryable failure
--    screen and Retry re-presents the same token into the same deterministic
--    collision. finishSignedIn returns before syncLocalIdentityOwner, so the
--    browser never claims the local data either; an hour later the grant is
--    dropped as abandoned and the rows stay stranded under a dead anon uid.
--
-- 2. It threw away the student's writing. On a conflicting opportunity the
--    losing interactions row was deleted outright — notes, remind_at,
--    last_contacted_at and its status history — while the summary counted only
--    the rows that moved.
--
-- 3. It deleted concierge requests nobody asked it to. Both waitlist writers
--    hardcode intent='apply_for_me', so (email, intent) is really (email): a
--    request for professor P went because the account had one for professor Q.
--
-- Rollback is `\i supabase/migrations/029_profile_save_cas.sql` for the
-- function (CREATE OR REPLACE, no signature change) and DROP TABLE for the
-- archive. Nothing here alters an existing column.

-- =========================================================================
-- Where a discarded interaction goes
-- =========================================================================
-- Same answer profile_versions already gives the profiles branch: the winner
-- stays current, the loser is preserved. Written ONLY by redeem_merge_grant,
-- which is SECURITY DEFINER, so the browser roles keep SELECT and nothing else.
CREATE TABLE IF NOT EXISTS public.interaction_merge_archive (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id        text NOT NULL,        -- the surviving owner (merge target)
  source_device_id text NOT NULL,        -- the account this row was living on
  opportunity_id   text NOT NULL,
  interaction      jsonb NOT NULL,       -- the discarded row, verbatim
  status_changes   jsonb NOT NULL DEFAULT '[]'::jsonb,
  archived_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_interaction_merge_archive_lookup
  ON public.interaction_merge_archive (device_id, opportunity_id, archived_at DESC);

ALTER TABLE public.interaction_merge_archive ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "interaction_merge_archive_select_own"
  ON public.interaction_merge_archive;
CREATE POLICY "interaction_merge_archive_select_own"
  ON public.interaction_merge_archive
  FOR SELECT USING (device_id = (select auth.uid()::text));

-- PUBLIC is revoked alongside the named roles for the reason 029 gives:
-- has_table_privilege('anon', ...) is true whenever PUBLIC holds it.
REVOKE INSERT, UPDATE, DELETE ON public.interaction_merge_archive
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON public.interaction_merge_archive TO anon, authenticated;

-- =========================================================================
-- Combining two notes for one opportunity
-- =========================================================================
-- Both were written by the same student. Keep the winner's first so the merged
-- text reads in the order the surviving row was already showing, and skip a
-- copy that is already contained in it. 005 caps notes at 2000 chars
-- (interactions_notes_length): a concatenation that would breach the cap leaves
-- the winner's notes ALONE rather than truncating the tail or aborting the
-- merge — the loser's full text is in interaction_merge_archive either way.
-- The separator carries no words on purpose: this string is written by the
-- database and can never be translated.
CREATE OR REPLACE FUNCTION public.merge_interaction_notes(p_keep text, p_other text)
RETURNS text
LANGUAGE sql
IMMUTABLE
AS $fn$
  SELECT CASE
    WHEN nullif(btrim(coalesce(p_other, '')), '') IS NULL THEN p_keep
    WHEN nullif(btrim(coalesce(p_keep,  '')), '') IS NULL THEN p_other
    WHEN position(btrim(p_other) in coalesce(p_keep, '')) > 0 THEN p_keep
    WHEN length(p_keep) + length(p_other) + 4 > 2000 THEN p_keep
    ELSE p_keep || E'\n\n— —\n' || p_other
  END;
$fn$;

REVOKE ALL ON FUNCTION public.merge_interaction_notes(text, text) FROM PUBLIC, anon;

-- =========================================================================
-- The merge itself: 029's function with the interactions and waitlist blocks
-- replaced. Every other block, and all four of 029's invariants (advisory lock
-- on both accounts in sorted order, target tombstone guard, profile_revision
-- adopt-vs-archive, every table moved), is carried forward unchanged.
-- =========================================================================
CREATE OR REPLACE FUNCTION public.redeem_merge_grant(p_token uuid, p_secret text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
  v_target          text := auth.uid()::text;
  v_target_email    text := nullif(lower(trim(auth.jwt() ->> 'email')), '');
  v_source          text;
  v_bound_email     text;
  v_secret_hash     text;
  v_expires         timestamptz;
  v_consumed        timestamptz;
  v_redeemed_by     text;
  v_redeemed_result jsonb;
  v_bound_ok        boolean;
  v_adopted         boolean := false;
  v_summary         jsonb := '{}'::jsonb;
  v_result          jsonb;
  n int;
BEGIN
  IF v_target IS NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: no authenticated session';
  END IF;

  -- Lock the grant so two concurrent redeems can't both consume it.
  SELECT source_device_id, target_email, secret_hash, expires_at, consumed_at,
         redeemed_by, redeemed_result
    INTO v_source, v_bound_email, v_secret_hash, v_expires, v_consumed,
         v_redeemed_by, v_redeemed_result
    FROM merge_grants WHERE token = p_token FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'redeem_merge_grant: invalid grant';
  END IF;

  -- Binding proof — possession of the secret (OAuth path) or the bound email
  -- (email path). Computed once so it is enforced identically whether this
  -- redemption is fresh or a replay of an already-consumed grant.
  v_bound_ok := (
    v_secret_hash IS NOT NULL
      AND p_secret IS NOT NULL
      AND encode(sha256(convert_to(p_secret, 'UTF8')), 'hex') = v_secret_hash
  ) OR (
    v_secret_hash IS NULL
      AND v_bound_email IS NOT NULL
      AND v_bound_email IS NOT DISTINCT FROM v_target_email
  );

  IF v_consumed IS NOT NULL THEN
    -- Idempotent replay: only for the exact account that redeemed it the
    -- first time, re-presenting the exact same proof. Everything else that
    -- reaches a consumed row fails closed, unchanged from pre-026 behavior.
    IF v_redeemed_by IS NOT DISTINCT FROM v_target AND v_bound_ok THEN
      RETURN v_redeemed_result;
    END IF;
    RAISE EXCEPTION 'redeem_merge_grant: grant already used';
  END IF;

  IF v_expires < now() THEN
    RAISE EXCEPTION 'redeem_merge_grant: grant expired';
  END IF;
  -- Binding is mandatory (mint enforces exactly one). An unbound grant must
  -- never be redeemable — reject outright rather than fall through to an
  -- unchecked move (defense in depth against a row created any other way).
  IF v_bound_email IS NULL AND v_secret_hash IS NULL THEN
    RAISE EXCEPTION 'redeem_merge_grant: unbound grant is not redeemable';
  END IF;
  IF NOT v_bound_ok THEN
    IF v_secret_hash IS NOT NULL THEN
      RAISE EXCEPTION 'redeem_merge_grant: grant not bound to this session';
    ELSE
      RAISE EXCEPTION 'redeem_merge_grant: grant not bound to this account';
    END IF;
  END IF;

  -- No-op case: same device. Nothing moves, so no profile lock is needed.
  IF v_source = v_target THEN
    v_result := jsonb_build_object('merged', false, 'reason', 'same_device');
    UPDATE merge_grants
      SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
      WHERE token = p_token;
    RETURN v_result;
  END IF;

  -- 027: the SAME key commit_profile_cas takes, on BOTH accounts, before the
  -- merged_devices scan and before anything reads `profiles`. This is what
  -- makes "target has no profile, adopt the source's" safe: a CAS on either
  -- account is either fully applied before this point or fully blocked until
  -- the merge commits and its own merged-away check can see the tombstone.
  -- Sorted so a merge of A->B and a merge of B->A cannot deadlock each other.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(v_source, v_target)));
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(v_source, v_target)));

  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_source) THEN
    v_result := jsonb_build_object('merged', false, 'reason', 'source_already_merged');
    UPDATE merge_grants
      SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
      WHERE token = p_token;
    RETURN v_result;
  END IF;
  -- 027: the TARGET must be alive too. Pre-027 only the source was checked,
  -- which left two ways to move data into an account that no longer exists:
  --   * reverse merge — A->B tombstones A; a later B->A passes the source
  --     check (B is not tombstoned) and moves everything BACK into the dead
  --     A, then tombstones B as well, leaving both accounts dead and the data
  --     reachable from neither;
  --   * chain onto a dead target — B->C tombstones B; a later A->B moves A's
  --     data into B, which C's owner will never see.
  -- Both are silent data loss, so this fails closed with a stable message and
  -- WITHOUT consuming the grant: raising rolls the whole call back, and the
  -- situation is recoverable (sign in to the account that actually survived).
  IF EXISTS (SELECT 1 FROM merged_devices WHERE source_device_id = v_target) THEN
    RAISE EXCEPTION 'redeem_merge_grant: target already merged';
  END IF;

  -- ---- per-table merge (byte-identical to 023/026 apart from profiles/
  -- profile_versions revision handling, below) -----------------------------
  -- Rows are moved by re-keying device_id (an UPDATE), never re-inserted, so
  -- the interactions status-change trigger (fires only on interaction_type
  -- change) stays quiet and row identities/histories are preserved.

  -- favorites: set union on (device_id, opportunity_id). Drop source dupes,
  -- move the rest.
  DELETE FROM favorites b USING favorites a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.opportunity_id = b.opportunity_id;
  UPDATE favorites SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('favorites', n);

  -- interactions: last-writer-wins by updated_at on (device_id, opportunity_id).
  -- NULL-safe: updated_at is nullable, so coalesce a floor in so a real
  -- timestamp always beats NULL (and NULL vs NULL keeps the target).
  --
  -- 034: the LOSER of a conflict is not a duplicate row. It carries the
  -- student's own notes, a remind_at, a last_contacted_at and its own status
  -- history (005 + 009), and 029 deleted all of it. Same answer the profiles
  -- branch below already gives, and for the same reason: the winner stays
  -- current, the loser is preserved rather than dropped.
  --
  -- Salvaged onto the winner: notes (appended) and last_contacted_at (latest).
  -- Both are monotone — more of the student's own record, never less.
  --
  -- remind_at is NOT salvaged by least(). It is one-shot state, not a value:
  -- push.py clears it to NULL on delivery, so NULL on the winner can mean
  -- "already fired", and a date in the past means "due and never delivered".
  -- Every merge source is an anonymous session (minting requires the
  -- is_anonymous claim), anonymous devices have no delivery channel, so their
  -- remind_at accumulates stale past dates that never fire and never clear.
  -- least() would pick exactly those over the account's live future date, and
  -- the next cron run would fire a reminder for something dealt with months
  -- ago and then clear it. So the winner keeps its own, and the loser's is
  -- adopted only when the winner has none AND the loser's is still ahead of us.
  --
  -- interaction_type is deliberately not salvaged either: last-writer-wins is
  -- the rule, and a combined status would be one the student never set. None
  -- of the salvage UPDATEs list it, so 009's AFTER UPDATE OF interaction_type
  -- trigger stays quiet, as 029 requires.
  --
  -- The summary keys are unchanged on purpose. `interactions` still counts
  -- rows that MOVED. That number was misleading only because the rows it did
  -- not count were being destroyed; now that nothing is, reporting movers is
  -- honest, and adding a second count that is not a subset of the first would
  -- put "we combined 2 of them" next to a "them" of 1.

  -- (1) source-wins conflicts: the TARGET's row loses. Archive it, salvage it
  --     onto the source row that is about to move, then drop it.
  INSERT INTO interaction_merge_archive
      (device_id, source_device_id, opportunity_id, interaction, status_changes)
    SELECT v_target, v_target, a.opportunity_id, to_jsonb(a),
           coalesce((
             SELECT jsonb_agg(to_jsonb(t) ORDER BY t.changed_at)
               FROM interaction_status_changes t
              WHERE t.device_id = v_target AND t.opportunity_id = a.opportunity_id
           ), '[]'::jsonb)
      FROM interactions a
      JOIN interactions b
        ON b.device_id = v_source AND b.opportunity_id = a.opportunity_id
     WHERE a.device_id = v_target
       AND coalesce(b.updated_at, '-infinity'::timestamptz)
         > coalesce(a.updated_at, '-infinity'::timestamptz);

  UPDATE interactions b
     SET notes             = merge_interaction_notes(b.notes, a.notes),
         last_contacted_at = greatest(b.last_contacted_at, a.last_contacted_at),
         remind_at         = CASE
                               WHEN b.remind_at IS NOT NULL THEN b.remind_at
                               WHEN a.remind_at > now() THEN a.remind_at
                               ELSE NULL
                             END
    FROM interactions a
   WHERE b.device_id = v_source AND a.device_id = v_target
     AND a.opportunity_id = b.opportunity_id
     AND coalesce(b.updated_at, '-infinity'::timestamptz)
       > coalesce(a.updated_at, '-infinity'::timestamptz);

  DELETE FROM interaction_status_changes t
    USING interactions a, interactions b
    WHERE t.device_id = v_target AND t.opportunity_id = a.opportunity_id
      AND a.device_id = v_target AND b.device_id = v_source
      AND a.opportunity_id = b.opportunity_id
      AND coalesce(b.updated_at, '-infinity'::timestamptz)
        > coalesce(a.updated_at, '-infinity'::timestamptz);
  DELETE FROM interactions a USING interactions b
    WHERE a.device_id = v_target AND b.device_id = v_source
      AND a.opportunity_id = b.opportunity_id
      AND coalesce(b.updated_at, '-infinity'::timestamptz)
        > coalesce(a.updated_at, '-infinity'::timestamptz);

  -- (2) every remaining conflict is target-wins: the SOURCE's row loses.
  INSERT INTO interaction_merge_archive
      (device_id, source_device_id, opportunity_id, interaction, status_changes)
    SELECT v_target, v_source, b.opportunity_id, to_jsonb(b),
           coalesce((
             SELECT jsonb_agg(to_jsonb(s) ORDER BY s.changed_at)
               FROM interaction_status_changes s
              WHERE s.device_id = v_source AND s.opportunity_id = b.opportunity_id
           ), '[]'::jsonb)
      FROM interactions b
      JOIN interactions a
        ON a.device_id = v_target AND a.opportunity_id = b.opportunity_id
     WHERE b.device_id = v_source;

  UPDATE interactions a
     SET notes             = merge_interaction_notes(a.notes, b.notes),
         last_contacted_at = greatest(a.last_contacted_at, b.last_contacted_at),
         remind_at         = CASE
                               WHEN a.remind_at IS NOT NULL THEN a.remind_at
                               WHEN b.remind_at > now() THEN b.remind_at
                               ELSE NULL
                             END
    FROM interactions b
   WHERE a.device_id = v_target AND b.device_id = v_source
     AND a.opportunity_id = b.opportunity_id;

  DELETE FROM interaction_status_changes s
    USING interactions b, interactions a
    WHERE s.device_id = v_source AND s.opportunity_id = b.opportunity_id
      AND b.device_id = v_source AND a.device_id = v_target
      AND b.opportunity_id = a.opportunity_id;
  DELETE FROM interactions b USING interactions a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND b.opportunity_id = a.opportunity_id;

  -- move the survivors + their now-coherent status history.
  UPDATE interactions SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('interactions', n);
  UPDATE interaction_status_changes SET device_id = v_target WHERE device_id = v_source;

  -- profiles (id = uid): keep target's; if target has none, adopt source's
  -- (revision sequence moves with the row — it is the same document under a
  -- new owner); otherwise preserve source's as a profile_version so nothing
  -- is lost. That archived copy is explicitly revision-less: it belongs to a
  -- sequence the target account never had, and stamping the target's numbers
  -- on it would make the history lie about what revision N contained.
  IF NOT EXISTS (SELECT 1 FROM profiles WHERE id = v_target) THEN
    UPDATE profiles SET id = v_target WHERE id = v_source;
    GET DIAGNOSTICS n = ROW_COUNT;
    v_adopted := n > 0;
    v_summary := v_summary || jsonb_build_object('profile',
      CASE WHEN n > 0 THEN 'adopted' ELSE 'none' END);
  ELSE
    INSERT INTO profile_versions (device_id, profile_data, created_at, profile_revision)
      SELECT v_target, profile_data, now(), NULL FROM profiles WHERE id = v_source;
    DELETE FROM profiles WHERE id = v_source;
    IF FOUND THEN
      v_summary := v_summary || jsonb_build_object('profile', 'kept_target_saved_other_as_version');
    ELSE
      v_summary := v_summary || jsonb_build_object('profile', 'kept_target');
    END IF;
  END IF;

  -- profile_versions: append-only; move all. Revisions survive the move only
  -- when the current row moved with them (adoption); otherwise they describe
  -- a sequence that no longer exists under this owner.
  IF v_adopted THEN
    UPDATE profile_versions SET device_id = v_target WHERE device_id = v_source;
  ELSE
    UPDATE profile_versions SET device_id = v_target, profile_revision = NULL
      WHERE device_id = v_source;
  END IF;

  -- saved_searches: no per-name uniqueness; move all (union).
  UPDATE saved_searches SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('saved_searches', n);

  -- match_feedback: keep target's verdict on conflict (no reliable recency
  -- column); move non-conflicting votes.
  DELETE FROM match_feedback b USING match_feedback a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.opportunity_id = b.opportunity_id;
  UPDATE match_feedback SET device_id = v_target WHERE device_id = v_source;

  -- push_subscriptions: dedup by endpoint.
  DELETE FROM push_subscriptions b USING push_subscriptions a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.endpoint = b.endpoint;
  UPDATE push_subscriptions SET device_id = v_target WHERE device_id = v_source;

  -- analytics_events: append-only; move all (keeps the tombstoned uid clean).
  UPDATE analytics_events SET device_id = v_target WHERE device_id = v_source;

  -- waitlist. 033 gave a concierge request the one thing it was missing —
  -- WHICH opportunity — plus a partial unique index on (device_id,
  -- opportunity_id) where opportunity_id IS NOT NULL. This block predates both
  -- and got two things wrong.
  --
  -- It dedups on (email, intent), and both writers hardcode
  -- intent='apply_for_me', so the key is really just the email: a source
  -- request for professor P was deleted because the account already held one
  -- for professor Q. That job simply vanished before any operator saw it.
  --
  -- And whatever survived was re-keyed straight into the target, so two
  -- accounts holding a request for the SAME professor under different emails
  -- collided with 033's index. unique_violation rolls back the ENTIRE merge,
  -- the grant is never consumed, and /auth/callback's Retry re-presents the
  -- same token into the same deterministic collision forever.
  --
  -- So: dedup targeted rows on the index's own key, and keep the (email,
  -- intent) rule only where 015's untargeted rows actually live.

  -- (1) untargeted (015-era) duplicates: the original rule, scoped to the rows
  --     it was always about.
  DELETE FROM waitlist b USING waitlist a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND b.opportunity_id IS NULL AND a.opportunity_id IS NULL
      AND coalesce(b.email, '') = coalesce(a.email, '') AND b.intent = a.intent;

  -- (2) the same target asked for twice is ONE standing request. Collapse it,
  --     but carry over what only the duplicate had: the earlier created_at
  --     (it has been standing since then) and an email, which may be the only
  --     way to reach the student.
  UPDATE waitlist a
     SET created_at = least(a.created_at, b.created_at),
         email      = coalesce(a.email, b.email)
    FROM waitlist b
   WHERE a.device_id = v_target AND b.device_id = v_source
     AND a.opportunity_id IS NOT NULL
     AND a.opportunity_id = b.opportunity_id;

  DELETE FROM waitlist b USING waitlist a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND b.opportunity_id IS NOT NULL
      AND a.opportunity_id = b.opportunity_id;

  -- Every targeted source row still standing names a target the account does
  -- not hold, and opportunity_id is unique within one device, so this can no
  -- longer collide with 033's index.
  UPDATE waitlist SET device_id = v_target WHERE device_id = v_source;

  -- feedback: append-only; move all.
  UPDATE feedback SET device_id = v_target WHERE device_id = v_source;

  -- resume_renovations (021): set union on (device_id, opportunity_id). The
  -- target's working doc for an opportunity is the user's active edit on the
  -- destination account, so keep it on conflict; drop source dupes, move the
  -- rest. (Symmetric with favorites/match_feedback conflict handling.)
  DELETE FROM resume_renovations b USING resume_renovations a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.opportunity_id = b.opportunity_id;
  UPDATE resume_renovations SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('resume_renovations', n);

  -- resume_renovation_versions (021): append-only; move all.
  UPDATE resume_renovation_versions SET device_id = v_target WHERE device_id = v_source;

  -- usage_events (021): append-only ledger; move all so post-merge quota
  -- accounting stays coherent under the surviving account.
  UPDATE usage_events SET device_id = v_target WHERE device_id = v_source;

  -- orders (019, added by 025/W14 — carried through every later redeem body
  -- so the FINAL function keeps it): a paid order made while anonymous must
  -- follow the merge. PK-keyed only; a plain re-key moves them all.
  UPDATE orders SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('orders', n);

  -- professor_follows (023): set union on (device_id, professor_id). Drop
  -- source dupes, move the rest — same conflict handling as favorites and
  -- the 021 resume tables on their UNIQUE constraints.
  DELETE FROM professor_follows b USING professor_follows a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.professor_id = b.professor_id;
  UPDATE professor_follows SET device_id = v_target WHERE device_id = v_source;
  GET DIAGNOSTICS n = ROW_COUNT;
  v_summary := v_summary || jsonb_build_object('professor_follows', n);

  -- professor_update_reads (023): read cursor per (device_id, professor_id).
  -- Keep the target's cursor on conflict (mirrors resume_renovations); at
  -- worst an already-seen update briefly shows unread again — never lost data.
  DELETE FROM professor_update_reads b USING professor_update_reads a
    WHERE b.device_id = v_source AND a.device_id = v_target
      AND a.professor_id = b.professor_id;
  UPDATE professor_update_reads SET device_id = v_target WHERE device_id = v_source;

  -- tracker-attachments: NOT moved in v1. Moving storage objects re-keys the
  -- backing bytes, which needs the Storage API (a service-role backend move),
  -- not raw SQL. We COUNT them so the client can honestly tell the user their
  -- files stayed on the other device (they're not lost, just not re-homed).
  SELECT count(*) INTO n FROM storage.objects
    WHERE bucket_id = 'tracker-attachments'
      AND (storage.foldername(name))[1] = v_source;
  v_summary := v_summary || jsonb_build_object('attachments_not_moved', n);

  v_result := jsonb_build_object('merged', true, 'summary', v_summary);

  -- Consume the grant (atomically recording who + the exact replayable
  -- result) and tombstone the source.
  UPDATE merge_grants
    SET consumed_at = now(), redeemed_by = v_target, redeemed_result = v_result
    WHERE token = p_token;
  INSERT INTO merged_devices (source_device_id, target_device_id, summary)
    VALUES (v_source, v_target, v_summary);

  RETURN v_result;
END;
$$;

REVOKE ALL ON FUNCTION public.redeem_merge_grant(uuid, text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.redeem_merge_grant(uuid, text) TO authenticated;
