-- Each link exposes the owner's selected, saved fields at one published revision.
-- A recipient cannot enumerate links or read private profile rows.
create table public.profile_shares (
  token uuid primary key,
  owner_id uuid not null references auth.users(id) on delete cascade,
  version integer not null check (version > 0),
  profile_revision integer not null,
  fields text[] not null,
  snapshot jsonb not null,
  expires_at timestamptz not null,
  revoked_at timestamptz,
  updated_at timestamptz not null default now()
);
create index profile_shares_by_owner on public.profile_shares(owner_id, updated_at desc);
alter table public.profile_shares enable row level security;
revoke all on public.profile_shares from public, anon, authenticated;
grant select on public.profile_shares to authenticated;
create policy profile_share_owner_read on public.profile_shares for select to authenticated
  using (owner_id = (select auth.uid()) and ((select auth.jwt())->>'is_anonymous') = 'false');

-- A snapshot is derived from the authenticated owner's stored profile. Only
-- names and levels leave a skills row; course sources and statuses stay private.
create function private.profile_share_preview(fields text[])
returns jsonb language plpgsql stable security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
  choices text[] := array['college','major','grade','intl','interests','skills','seeking','weight','courses'];
  data jsonb;
  rev integer;
  snapshot jsonb := '{}'::jsonb;
  key text;
  value jsonb;
  result jsonb;
  item jsonb;
  item_name text;
begin
  if uid is null or auth.jwt()->>'is_anonymous' is distinct from 'false' then
    raise insufficient_privilege using message = 'permanent_account_required';
  end if;
  if fields is null or cardinality(fields) not between 1 and cardinality(choices)
     or array_position(fields, null) is not null or not (fields <@ choices)
     or cardinality(fields) <> (select count(distinct f) from unnest(fields) f) then
    raise invalid_parameter_value using message = 'invalid_share_fields';
  end if;
  select profile_data, revision into data, rev from public.profiles where id = uid::text;
  if not found then raise no_data_found using message = 'saved_profile_required'; end if;

  foreach key in array fields loop
    case key
    when 'skills', 'courses', 'seeking' then
      value := case key when 'skills' then data->'skills'
        when 'courses' then coalesce(nullif(data->'courses','null'::jsonb),data->'coursework')
        else data->'seeking_types' end;
      value := coalesce(nullif(value,'null'::jsonb),'[]'::jsonb);
      if jsonb_typeof(value) <> 'array' then raise invalid_parameter_value using message = 'invalid_share_source'; end if;
      result := '[]'::jsonb;
      for item in select * from jsonb_array_elements(value) loop
        item_name := case when jsonb_typeof(item) = 'string' then item #>> '{}'
          when key in ('skills','courses') and jsonb_typeof(item->'name') = 'string' then item->>'name' end;
        if item_name is null then raise invalid_parameter_value using message = 'invalid_share_source'; end if;
        if key = 'skills' then
          result := result || jsonb_build_array(jsonb_build_object('n',item_name,'l',
            case when item->>'level' in ('experienced','expert') then item->>'level' else 'beginner' end));
        else
          result := result || jsonb_build_array(item_name);
        end if;
      end loop;
    when 'intl' then
      result := coalesce(nullif(data->'is_international','null'::jsonb),'false'::jsonb);
      if jsonb_typeof(result) <> 'boolean' then raise invalid_parameter_value using message = 'invalid_share_source'; end if;
    when 'weight' then
      result := coalesce(nullif(data->'search_weight','null'::jsonb),'50'::jsonb);
      if jsonb_typeof(result) <> 'number' or (result::text)::numeric not between 0 and 100
         or trunc((result::text)::numeric) <> (result::text)::numeric then
        raise invalid_parameter_value using message = 'invalid_share_source';
      end if;
    else
      value := data->(case when key = 'interests' then 'research_interests' else key end);
      result := coalesce(nullif(value,'null'::jsonb),'""'::jsonb);
      if jsonb_typeof(result) <> 'string' then raise invalid_parameter_value using message = 'invalid_share_source'; end if;
    end case;
    snapshot := snapshot || jsonb_build_object(key,result);
  end loop;
  return jsonb_build_object('profile_revision',rev,'snapshot',snapshot);
end;
$$;
revoke all on function private.profile_share_preview(text[]) from public, anon, authenticated;

create function public.preview_profile_share(p_fields text[])
returns jsonb language sql stable security definer set search_path = '' as $$
  select private.profile_share_preview(p_fields);
$$;
revoke all on function public.preview_profile_share(text[]) from public, anon;
grant execute on function public.preview_profile_share(text[]) to authenticated;

-- A sender supplies a random token once. Retrying a successful create or
-- replace after losing the response returns that version without advancing it.
create function public.publish_profile_share(p_token uuid, p_expected_version integer, p_fields text[],
  p_expires_at timestamptz, p_profile_revision integer)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  uid uuid := auth.uid();
  preview jsonb;
  saved public.profile_shares%rowtype;
begin
  preview := private.profile_share_preview(p_fields);
  if p_token is null or p_expected_version is null or p_expected_version < 0
      or p_expires_at is null or not isfinite(p_expires_at) then
    raise invalid_parameter_value using message = 'invalid_share_request';
  end if;
  -- Serialize creates, replacements and revocations of this link.
  perform pg_advisory_xact_lock(hashtextextended('ofe-share:' || p_token::text,0));
  select * into saved from public.profile_shares where token = p_token;
  if found and (saved.owner_id <> uid or saved.revoked_at is not null) then
    return jsonb_build_object('status','unavailable');
  end if;
  if saved.version = p_expected_version + 1 and saved.profile_revision = p_profile_revision
     and saved.fields = p_fields and saved.expires_at = p_expires_at then
    return jsonb_build_object('status','published','version',saved.version);
  end if;
  if p_expires_at <= clock_timestamp() then raise invalid_parameter_value using message = 'future_expiry_required'; end if;
  if (preview->>'profile_revision')::integer is distinct from p_profile_revision then
    return jsonb_build_object('status','profile_changed');
  end if;
  if coalesce(saved.version,0) <> p_expected_version then return jsonb_build_object('status','conflict'); end if;
  if p_expected_version = 0 then
    insert into public.profile_shares(token,owner_id,version,profile_revision,fields,snapshot,expires_at)
      values (p_token,uid,1,p_profile_revision,p_fields,preview->'snapshot',p_expires_at);
  else
    update public.profile_shares set version = version+1, profile_revision = p_profile_revision,
      fields = p_fields, snapshot = preview->'snapshot', expires_at = p_expires_at, updated_at = now() where token = p_token;
  end if;
  return jsonb_build_object('status','published','version',p_expected_version+1);
end;
$$;
revoke all on function public.publish_profile_share(uuid,integer,text[],timestamptz,integer) from public, anon;
grant execute on function public.publish_profile_share(uuid,integer,text[],timestamptz,integer) to authenticated;

create function public.revoke_profile_share(p_token uuid,p_expected_version integer)
returns jsonb language plpgsql security definer set search_path = '' as $$
declare
  saved public.profile_shares%rowtype;
begin
  if auth.uid() is null or auth.jwt()->>'is_anonymous' is distinct from 'false' then
    raise insufficient_privilege using message = 'permanent_account_required';
  end if;
  perform pg_advisory_xact_lock(hashtextextended('ofe-share:' || p_token::text,0));
  select * into saved from public.profile_shares where token=p_token and owner_id=auth.uid();
  if not found then return jsonb_build_object('status','unavailable'); end if;
  if saved.revoked_at is null then
    if saved.version is distinct from p_expected_version then return jsonb_build_object('status','conflict'); end if;
    update public.profile_shares set revoked_at=now(),updated_at=now(),version=version+1,snapshot='{}'::jsonb
      where token=p_token;
  end if;
  return jsonb_build_object('status','revoked');
end;
$$;
revoke all on function public.revoke_profile_share(uuid,integer) from public, anon;
grant execute on function public.revoke_profile_share(uuid,integer) to authenticated;

-- A new lookup is required before acceptance. A previously displayed version
-- is never silently replaced with material the recipient did not preview.
create function public.resolve_profile_share(p_token uuid,p_expected_version integer default null)
returns jsonb language sql stable security definer set search_path = '' as $$
  select coalesce((select case when p_expected_version is not null and p_expected_version <> version
      then jsonb_build_object('status','changed')
      else jsonb_build_object('status','active','version',version,'expires_at',expires_at,'snapshot',snapshot) end
    from public.profile_shares where token=p_token and revoked_at is null and expires_at>statement_timestamp()),
    jsonb_build_object('status','unavailable'));
$$;
revoke all on function public.resolve_profile_share(uuid,integer) from public;
grant execute on function public.resolve_profile_share(uuid,integer) to anon,authenticated;
