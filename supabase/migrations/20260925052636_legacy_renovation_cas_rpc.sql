-- Legacy bullet-based resumes remain separate from full_resume/v1.
-- Browser table access stays closed. Four bounded RPCs are the only new API.
ALTER TABLE public.resume_renovations
  ADD COLUMN revision bigint NOT NULL DEFAULT 1 CHECK (revision BETWEEN 1 AND 9007199254740991),
  ADD COLUMN owner_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  ADD CONSTRAINT renovation_owner_matches_device CHECK (owner_id IS NULL OR device_id = owner_id::text);
ALTER TABLE public.resume_renovation_versions
  ADD COLUMN owner_id uuid REFERENCES auth.users(id) ON DELETE CASCADE,
  ADD COLUMN revision bigint CHECK (revision BETWEEN 1 AND 9007199254740991),
  ADD COLUMN base_snapshot jsonb,
  ADD COLUMN method text,
  ADD COLUMN warnings jsonb,
  ADD COLUMN snapshot_kind text NOT NULL DEFAULT 'legacy_doc' CHECK (snapshot_kind IN ('legacy_doc', 'complete')),
  ADD COLUMN source_revision bigint CHECK (source_revision BETWEEN 1 AND 9007199254740991),
  ADD COLUMN source_updated_at timestamptz,
  ADD CONSTRAINT renovation_version_owner_matches_device CHECK (owner_id IS NULL OR device_id = owner_id::text);
-- Never cast/claim old arbitrary device strings. Unmatched historical rows
-- remain preserved and inaccessible; an auth UUID is the only owned namespace.
UPDATE public.resume_renovations r SET owner_id = u.id FROM auth.users u WHERE r.device_id = u.id::text;
UPDATE public.resume_renovation_versions r SET owner_id = u.id FROM auth.users u WHERE r.device_id = u.id::text;
-- The old best-effort history may have missed the actual working document.
-- Preserve the exact four fields without guessing anything about old history.
INSERT INTO public.resume_renovation_versions
  (device_id, owner_id, opportunity_id, doc, base_snapshot, method, warnings, revision, created_at, snapshot_kind)
SELECT device_id, owner_id, opportunity_id, doc, base_snapshot, method, warnings, revision, updated_at, 'complete'
FROM public.resume_renovations;
CREATE INDEX renovation_versions_page_idx ON public.resume_renovation_versions (device_id, opportunity_id, created_at DESC, id DESC);
CREATE INDEX renovation_owner_idx ON public.resume_renovations (owner_id);
CREATE INDEX renovation_versions_owner_idx ON public.resume_renovation_versions (owner_id);
-- In particular, do not regrant SELECT or install browser policies.
REVOKE ALL ON public.resume_renovations, public.resume_renovation_versions FROM PUBLIC, anon, authenticated;

CREATE FUNCTION private.renovation_owner(p_expected_owner text) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE uid uuid := auth.uid();
BEGIN
  IF uid IS NULL OR p_expected_owner IS DISTINCT FROM uid::text THEN
    RAISE EXCEPTION 'renovation_owner_unavailable' USING ERRCODE = '42501';
  END IF;
  -- Match the merge lock order: owner advisory, auth row, material rows.
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || uid::text));
  -- A stale JWT cannot outlive its deleted auth account. The row lock also
  -- serializes this transaction with actual account deletion.
  PERFORM 1 FROM auth.users WHERE id = uid FOR KEY SHARE;
  IF NOT FOUND THEN RAISE EXCEPTION 'renovation_owner_unavailable' USING ERRCODE = '42501'; END IF;
  IF EXISTS (SELECT 1 FROM public.merged_devices WHERE source_device_id = uid::text) THEN
    RAISE EXCEPTION 'renovation_owner_unavailable' USING ERRCODE = '42501';
  END IF;
  RETURN uid;
END;
$$;
REVOKE ALL ON FUNCTION private.renovation_owner(text) FROM PUBLIC, anon, authenticated;

CREATE FUNCTION private.renovation_target(p_id text) RETURNS void
LANGUAGE plpgsql SET search_path = '' AS $$
BEGIN
  IF p_id IS NULL OR length(p_id) NOT BETWEEN 1 AND 200 OR btrim(p_id) = '' THEN
    RAISE EXCEPTION 'invalid_renovation_request' USING ERRCODE = '22023';
  END IF;
END;
$$;
REVOKE ALL ON FUNCTION private.renovation_target(text) FROM PUBLIC, anon, authenticated;

CREATE FUNCTION private.renovation_payload(r public.resume_renovations) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
 SELECT jsonb_build_object('doc', r.doc, 'base_snapshot', r.base_snapshot, 'method', r.method, 'warnings', r.warnings);
$$;
CREATE FUNCTION private.renovation_current(r public.resume_renovations) RETURNS jsonb
LANGUAGE sql IMMUTABLE SET search_path = '' AS $$
 SELECT jsonb_build_object('owner_id', r.owner_id, 'opportunity_id', r.opportunity_id,
   'revision', r.revision, 'payload', private.renovation_payload(r), 'updated_at', r.updated_at);
$$;
REVOKE ALL ON FUNCTION private.renovation_payload(public.resume_renovations), private.renovation_current(public.resume_renovations) FROM PUBLIC, anon, authenticated;

CREATE FUNCTION private.read_renovation(p_expected_owner text, p_opportunity_id text) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE uid uuid; r public.resume_renovations%ROWTYPE;
BEGIN
  uid := private.renovation_owner(p_expected_owner);
  PERFORM private.renovation_target(p_opportunity_id);
  SELECT * INTO r FROM public.resume_renovations WHERE owner_id = uid AND device_id = uid::text AND opportunity_id = p_opportunity_id;
  IF NOT FOUND THEN RETURN jsonb_build_object('status', 'absent'); END IF;
  RETURN jsonb_build_object('status', 'found', 'current', private.renovation_current(r));
END;
$$;

CREATE FUNCTION private.save_renovation_cas(p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_payload jsonb) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE uid uuid; r public.resume_renovations%ROWTYPE; next_revision bigint; stamp timestamptz;
BEGIN
  uid := private.renovation_owner(p_expected_owner);
  PERFORM private.renovation_target(p_opportunity_id);
  IF p_expected_revision IS NULL OR p_expected_revision NOT BETWEEN 0 AND 9007199254740991
    OR p_payload IS NULL OR jsonb_typeof(p_payload) IS DISTINCT FROM 'object' THEN
    RAISE EXCEPTION 'invalid_renovation_payload' USING ERRCODE = '22023';
  END IF;
  IF NOT (p_payload ?& ARRAY['doc','base_snapshot','method','warnings'])
    OR p_payload - ARRAY['doc','base_snapshot','method','warnings'] <> '{}'::jsonb
    OR jsonb_typeof(p_payload->'doc') IS DISTINCT FROM 'object'
    OR jsonb_typeof(p_payload->'base_snapshot') IS DISTINCT FROM 'object'
    OR jsonb_typeof(p_payload->'method') NOT IN ('string','null')
    OR jsonb_typeof(p_payload->'warnings') IS DISTINCT FROM 'array'
    OR private.target_resume_json_bytes(p_payload) > 2097152 THEN
    RAISE EXCEPTION 'invalid_renovation_payload' USING ERRCODE = '22023';
  END IF;
  IF EXISTS (SELECT 1 FROM jsonb_array_elements(p_payload->'warnings') x WHERE jsonb_typeof(x) <> 'string') THEN
    RAISE EXCEPTION 'invalid_renovation_payload' USING ERRCODE = '22023';
  END IF;
  -- No conversion to full_resume, no signature invention. Shape below merely
  -- rejects another document family; the client validates legacy semantics.
  IF p_payload->'doc'->>'kind' = 'full_resume'
    OR jsonb_typeof(p_payload->'doc'->'sections') IS DISTINCT FROM 'array' THEN
    RAISE EXCEPTION 'invalid_renovation_payload' USING ERRCODE = '22023';
  END IF;
  SELECT * INTO r FROM public.resume_renovations WHERE device_id = uid::text AND opportunity_id = p_opportunity_id FOR UPDATE;
  IF NOT FOUND THEN
    IF p_expected_revision <> 0 THEN RETURN jsonb_build_object('status', 'missing'); END IF;
    next_revision := 1;
  ELSE
    IF r.owner_id IS DISTINCT FROM uid THEN RAISE EXCEPTION 'renovation_owner_unavailable' USING ERRCODE = '42501'; END IF;
    IF private.renovation_payload(r) = p_payload AND r.revision IN (p_expected_revision, p_expected_revision + 1) THEN
      RETURN jsonb_build_object('status', 'unchanged', 'current', private.renovation_current(r));
    END IF;
    IF r.revision <> p_expected_revision THEN
      RETURN jsonb_build_object('status', 'conflict', 'current', private.renovation_current(r));
    END IF;
    IF r.revision >= 9007199254740991 THEN RAISE EXCEPTION 'renovation_revision_limit' USING ERRCODE = '22023'; END IF;
    next_revision := r.revision + 1;
  END IF;
  stamp := clock_timestamp(); -- after owner/current locks, never an earlier queued request time
  INSERT INTO public.resume_renovations(owner_id,device_id,opportunity_id,revision,doc,base_snapshot,method,warnings,updated_at)
    VALUES(uid,uid::text,p_opportunity_id,next_revision,p_payload->'doc',p_payload->'base_snapshot',p_payload->>'method',p_payload->'warnings',stamp)
    ON CONFLICT(device_id,opportunity_id) DO UPDATE SET
      revision=EXCLUDED.revision,doc=EXCLUDED.doc,base_snapshot=EXCLUDED.base_snapshot,
      method=EXCLUDED.method,warnings=EXCLUDED.warnings,updated_at=EXCLUDED.updated_at
    RETURNING * INTO r;
  INSERT INTO public.resume_renovation_versions(owner_id,device_id,opportunity_id,revision,doc,base_snapshot,method,warnings,created_at,snapshot_kind)
    VALUES(uid,uid::text,p_opportunity_id,r.revision,r.doc,r.base_snapshot,r.method,r.warnings,stamp,'complete');
  RETURN jsonb_build_object('status','saved','current',private.renovation_current(r));
END;
$$;

CREATE FUNCTION private.list_renovation_versions(p_expected_owner text, p_opportunity_id text,
  p_before_created_at timestamptz DEFAULT NULL, p_before_id uuid DEFAULT NULL, p_limit int DEFAULT 20) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE uid uuid; items jsonb; total int; last_item jsonb;
BEGIN
  uid := private.renovation_owner(p_expected_owner);
  PERFORM private.renovation_target(p_opportunity_id);
  IF p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 50 OR (p_before_created_at IS NULL) <> (p_before_id IS NULL)
    OR (p_before_created_at IS NOT NULL AND NOT isfinite(p_before_created_at)) THEN
    RAISE EXCEPTION 'invalid_renovation_request' USING ERRCODE = '22023';
  END IF;
  SELECT coalesce(jsonb_agg(jsonb_build_object('id',v.id,'created_at',v.created_at,'revision',v.revision,
    'snapshot_kind',v.snapshot_kind,'source_revision',v.source_revision,'source_updated_at',v.source_updated_at)
    ORDER BY v.created_at DESC,v.id DESC),'[]'::jsonb),count(*) INTO items,total
    FROM (SELECT * FROM public.resume_renovation_versions WHERE owner_id=uid AND device_id=uid::text AND opportunity_id=p_opportunity_id
      AND (p_before_created_at IS NULL OR (created_at,id)<(p_before_created_at,p_before_id))
      ORDER BY created_at DESC,id DESC LIMIT p_limit+1) v;
  IF total > p_limit THEN
    items := items - p_limit; last_item := items->(p_limit-1);
    RETURN jsonb_build_object('items',items,'next_cursor',jsonb_build_object('created_at',last_item->'created_at','id',last_item->'id'));
  END IF;
  RETURN jsonb_build_object('items',items,'next_cursor',NULL);
END;
$$;

CREATE FUNCTION private.get_renovation_version(p_expected_owner text, p_opportunity_id text, p_version_id uuid) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE uid uuid; v public.resume_renovation_versions%ROWTYPE;
BEGIN
  uid := private.renovation_owner(p_expected_owner);
  PERFORM private.renovation_target(p_opportunity_id);
  IF p_version_id IS NULL THEN RAISE EXCEPTION 'invalid_renovation_request' USING ERRCODE = '22023'; END IF;
  SELECT * INTO v FROM public.resume_renovation_versions WHERE owner_id=uid AND device_id=uid::text AND opportunity_id=p_opportunity_id AND id=p_version_id;
  IF NOT FOUND THEN RETURN jsonb_build_object('status','absent'); END IF;
  RETURN jsonb_build_object('status','found','version',jsonb_build_object(
    'owner_id',v.owner_id,'opportunity_id',v.opportunity_id,'id',v.id,'created_at',v.created_at,'revision',v.revision,
    'snapshot_kind',v.snapshot_kind,'source_revision',v.source_revision,'source_updated_at',v.source_updated_at,
    'payload',jsonb_build_object('doc',v.doc,'base_snapshot',v.base_snapshot,'method',v.method,'warnings',v.warnings)));
END;
$$;

CREATE FUNCTION public.read_renovation(p_expected_owner text, p_opportunity_id text) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.read_renovation(p_expected_owner,p_opportunity_id);
$$;
REVOKE ALL ON FUNCTION private.read_renovation(text,text), public.read_renovation(text,text) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.read_renovation(text,text), public.read_renovation(text,text) TO authenticated;

CREATE FUNCTION public.save_renovation_cas(p_expected_owner text, p_opportunity_id text, p_expected_revision bigint, p_payload jsonb) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.save_renovation_cas(p_expected_owner,p_opportunity_id,p_expected_revision,p_payload);
$$;
REVOKE ALL ON FUNCTION private.save_renovation_cas(text,text,bigint,jsonb), public.save_renovation_cas(text,text,bigint,jsonb) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.save_renovation_cas(text,text,bigint,jsonb), public.save_renovation_cas(text,text,bigint,jsonb) TO authenticated;

CREATE FUNCTION public.list_renovation_versions(p_expected_owner text, p_opportunity_id text, p_before_created_at timestamptz DEFAULT NULL, p_before_id uuid DEFAULT NULL, p_limit int DEFAULT 20) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.list_renovation_versions(p_expected_owner,p_opportunity_id,p_before_created_at,p_before_id,p_limit);
$$;
REVOKE ALL ON FUNCTION private.list_renovation_versions(text,text,timestamptz,uuid,int), public.list_renovation_versions(text,text,timestamptz,uuid,int) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.list_renovation_versions(text,text,timestamptz,uuid,int), public.list_renovation_versions(text,text,timestamptz,uuid,int) TO authenticated;

CREATE FUNCTION public.get_renovation_version(p_expected_owner text, p_opportunity_id text, p_version_id uuid) RETURNS jsonb
LANGUAGE sql SECURITY INVOKER SET search_path = '' AS $$
  SELECT private.get_renovation_version(p_expected_owner,p_opportunity_id,p_version_id);
$$;
REVOKE ALL ON FUNCTION private.get_renovation_version(text,text,uuid), public.get_renovation_version(text,text,uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION private.get_renovation_version(text,text,uuid), public.get_renovation_version(text,text,uuid) TO authenticated;

-- Called in the existing Flow B transaction, before it could discard a
-- source working row. All other Flow B behavior is preserved below.
CREATE FUNCTION private.merge_legacy_renovations(p_source text,p_target text) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE s public.resume_renovations%ROWTYPE; t public.resume_renovations%ROWTYPE;
  target_uid uuid; locked_accounts int; moved int := 0; stamp timestamptz;
BEGIN
  IF NOT EXISTS(SELECT 1 FROM public.resume_renovations WHERE device_id=p_source)
    AND NOT EXISTS(SELECT 1 FROM public.resume_renovation_versions WHERE device_id=p_source) THEN RETURN 0; END IF;
  target_uid := auth.uid();
  IF target_uid IS NULL OR p_target IS DISTINCT FROM target_uid::text OR p_source=p_target
    OR NOT EXISTS(SELECT 1 FROM auth.users WHERE id=target_uid) THEN
    RAISE EXCEPTION 'renovation_owner_unavailable' USING ERRCODE='42501';
  END IF;
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || least(p_source,p_target)));
  PERFORM pg_advisory_xact_lock(hashtext('ofe-profile:' || greatest(p_source,p_target)));
  -- The same advisory -> auth -> material order as every new RPC. Lock both
  -- accounts before touching either material so auth deletion cannot cascade
  -- between preserving source history and moving the current row.
  PERFORM id FROM auth.users WHERE id IN (p_source::uuid,target_uid) ORDER BY id FOR KEY SHARE;
  GET DIAGNOSTICS locked_accounts = ROW_COUNT;
  IF locked_accounts <> 2 THEN RAISE EXCEPTION 'renovation_owner_unavailable' USING ERRCODE='42501'; END IF;
  FOR s IN SELECT * FROM public.resume_renovations WHERE device_id=p_source ORDER BY opportunity_id FOR UPDATE LOOP
    -- Preserve even old best-effort saves with no matching history. Avoid a
    -- duplicate if a complete after-image already exists for this current.
    IF NOT EXISTS(SELECT 1 FROM public.resume_renovation_versions v WHERE v.device_id=p_source
      AND v.opportunity_id=s.opportunity_id AND v.snapshot_kind='complete' AND v.revision=s.revision
      AND v.doc=s.doc AND v.base_snapshot=s.base_snapshot AND v.method IS NOT DISTINCT FROM s.method AND v.warnings=s.warnings) THEN
      INSERT INTO public.resume_renovation_versions(device_id,owner_id,opportunity_id,revision,doc,base_snapshot,method,warnings,created_at,snapshot_kind)
        VALUES(p_source,s.owner_id,s.opportunity_id,s.revision,s.doc,s.base_snapshot,s.method,s.warnings,s.updated_at,'complete');
    END IF;
    SELECT * INTO t FROM public.resume_renovations WHERE device_id=p_target AND opportunity_id=s.opportunity_id FOR UPDATE;
    IF NOT FOUND THEN
      UPDATE public.resume_renovations SET device_id=p_target,owner_id=target_uid WHERE id=s.id;
      moved := moved+1;
    ELSE
      IF t.revision>=9007199254740991 THEN RAISE EXCEPTION 'renovation_revision_limit' USING ERRCODE='22023'; END IF;
      -- The destination wins, but bump it so stale destination writers must
      -- review the merge instead of silently overwriting its result.
      stamp := clock_timestamp();
      UPDATE public.resume_renovations SET owner_id=target_uid,revision=revision+1,updated_at=stamp WHERE id=t.id RETURNING * INTO t;
      INSERT INTO public.resume_renovation_versions(device_id,owner_id,opportunity_id,revision,doc,base_snapshot,method,warnings,created_at,snapshot_kind)
        VALUES(p_target,target_uid,t.opportunity_id,t.revision,t.doc,t.base_snapshot,t.method,t.warnings,stamp,'complete');
      DELETE FROM public.resume_renovations WHERE id=s.id;
    END IF;
  END LOOP;
  -- UUID identities and all payload bytes survive. A source revision is not
  -- part of the destination sequence; preserve provenance instead of relabeling.
  UPDATE public.resume_renovation_versions SET device_id=p_target,owner_id=target_uid,
    source_revision=coalesce(source_revision,revision),
    source_updated_at=coalesce(source_updated_at,created_at),revision=NULL WHERE device_id=p_source;
  RETURN moved;
END;
$$;
REVOKE ALL ON FUNCTION private.merge_legacy_renovations(text,text) FROM PUBLIC, anon, authenticated;

-- Effective 034 merge copied exactly except its legacy renovation block.
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

  -- Atomically preserve complete source current + history before draining it.
  n := private.merge_legacy_renovations(v_source, v_target);
  v_summary := v_summary || jsonb_build_object('resume_renovations', n);

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
