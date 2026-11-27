-- Replay the public sharing lifecycle against a migrated database with local Auth stubs.
\set ON_ERROR_STOP on
begin;
insert into auth.users(id) values ('52000000-0000-4000-8000-000000000001'),
                                  ('52000000-0000-4000-8000-000000000002');
insert into public.profiles(id,profile_data,revision) values (
  '52000000-0000-4000-8000-000000000001',
  '{"name":"Private sender","skills":[{"name":"Python","source":"github","evidence":"private","level":"expert"}]}',1
);

set local role authenticated;
select set_config('test.uid','52000000-0000-4000-8000-000000000001',true);
select set_config('test.jwt','{"is_anonymous":false}',true);
do $$
declare
  owner uuid := auth.uid();
  link uuid := '52000000-0000-4000-8000-000000000003';
  until_at timestamptz := now() + interval '1 day';
  fields text[] := array['skills'];
  payload jsonb;
begin
  payload := public.preview_profile_share(owner, fields);
  assert payload = '{"snapshot":{"skills":[{"n":"Python","l":"expert"}]},"profile_revision":1}'::jsonb;
  assert public.publish_profile_share(owner,link,0,fields,until_at,0)->>'status' = 'profile_changed';
  payload := public.publish_profile_share(owner,link,0,fields,until_at,1);
  assert payload = '{"status":"published","version":1}'::jsonb;
  assert public.publish_profile_share(owner,link,0,fields,until_at,1) = payload;
  assert public.publish_profile_share(owner,link,1,array['major'],until_at,1)->>'version' = '2';
  assert public.resolve_profile_share(link,1)->>'status' = 'changed';
  assert public.resolve_profile_share(link,2)->'snapshot' = '{"major":""}'::jsonb;
end $$;

select set_config('test.uid','52000000-0000-4000-8000-000000000002',true);
do $$
begin
  assert not exists(select from public.profile_shares);
  assert public.revoke_profile_share('52000000-0000-4000-8000-000000000003',2)->>'status' = 'unavailable';
end $$;

set local role anon;
do $$
begin
  assert public.resolve_profile_share('52000000-0000-4000-8000-000000000003',2)->>'status' = 'active';
end $$;
set local role authenticated;
select set_config('test.uid','52000000-0000-4000-8000-000000000001',true);
select set_config('test.jwt','{"is_anonymous":true}',true);
do $$
begin
  begin
    perform public.preview_profile_share(auth.uid(),array['name']);
    raise exception 'Guest publisher accepted';
  exception when insufficient_privilege then null;
  end;
end $$;
select set_config('test.jwt','{"is_anonymous":false}',true);
do $$
declare link uuid := '52000000-0000-4000-8000-000000000003';
begin
  assert public.revoke_profile_share(link,1)->>'status' = 'conflict';
  assert public.revoke_profile_share(link,2)->>'status' = 'revoked';
  assert public.revoke_profile_share(link,2)->>'status' = 'revoked';
  assert public.resolve_profile_share(link)->>'status' = 'unavailable';
  assert (select snapshot = '{}'::jsonb from public.profile_shares where token = link);
end $$;
rollback;
