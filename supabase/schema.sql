-- Skylance backend schema (Supabase project "skylance"). Reference copy of what is deployed.
-- Run in the SQL editor of a fresh project to recreate it. The app only calls the three public functions.

create table public.players (
  code text primary key check (code ~ '^[a-z0-9]{6}$'),
  secret uuid not null,
  created_at timestamptz not null default now()
);
create table public.referrals (
  id bigint generated always as identity primary key,
  inviter text not null references public.players(code),
  invitee text not null unique references public.players(code),
  claimed boolean not null default false,
  created_at timestamptz not null default now()
);
create table public.rate_log (
  id bigint generated always as identity primary key,
  kind text not null check (kind in ('register','claim')),
  who text not null,
  created_at timestamptz not null default now()
);
create table public.purchases (
  token text primary key,
  code text not null references public.players(code),
  product text not null,
  gems int not null check (gems > 0),
  order_id text,
  test boolean not null default false,
  created_at timestamptz not null default now()
);
create index players_created on public.players (created_at);
create index rate_log_kind_who_time on public.rate_log (kind, who, created_at);
create index purchases_code on public.purchases (code);

-- Locked tables: row-level security on, no policies, no grants. Nobody can read or write them through the API.
alter table public.players enable row level security;
alter table public.referrals enable row level security;
alter table public.rate_log enable row level security;
alter table public.purchases enable row level security;
revoke all on public.players, public.referrals, public.rate_log, public.purchases from anon, authenticated, public;

create or replace function public._caller_hash() returns text language plpgsql stable security definer set search_path to '' as $$
declare h json; ip text;
begin
  begin h := current_setting('request.headers', true)::json; exception when others then return null; end;
  if h is null then return null; end if;
  ip := coalesce(h->>'cf-connecting-ip', split_part(h->>'x-forwarded-for', ',', 1));
  ip := nullif(trim(ip), '');
  if ip is null then return null; end if;
  return encode(sha256(convert_to('skylance:' || ip, 'UTF8')), 'hex');
end $$;

create or replace function public._rate_ok(p_kind text, p_limit int, p_window interval) returns boolean language plpgsql security definer set search_path to '' as $$
declare w text := public._caller_hash(); n int;
begin
  if random() < 0.02 then delete from public.rate_log where created_at < now() - interval '2 days'; end if;
  if w is null then return true; end if;
  select count(*) into n from public.rate_log where kind = p_kind and who = w and created_at > now() - p_window;
  if n >= p_limit then return false; end if;
  insert into public.rate_log(kind, who) values (p_kind, w);
  return true;
end $$;

create or replace function public.register_player(p_code text, p_secret uuid) returns boolean language plpgsql security definer set search_path to '' as $$
declare existing uuid;
begin
  if p_code is null or p_code !~ '^[a-z0-9]{6}$' or p_secret is null then return false; end if;
  select secret into existing from public.players where code = p_code;
  if existing is null then
    if not public._rate_ok('register', 30, interval '1 hour') then return false; end if;
    if (select count(*) from public.players where created_at > now() - interval '10 minutes') >= 3000 then return false; end if;
    insert into public.players(code, secret) values (p_code, p_secret) on conflict (code) do nothing;
    select secret into existing from public.players where code = p_code;
  end if;
  return existing = p_secret;
end $$;

create or replace function public.claim_referral(p_invitee text, p_secret uuid, p_inviter text) returns boolean language plpgsql security definer set search_path to '' as $$
declare today_count int;
begin
  if p_inviter is null or p_invitee is null or p_inviter = p_invitee or p_inviter !~ '^[a-z0-9]{6}$' then return false; end if;
  if not exists (select 1 from public.players where code = p_invitee and secret = p_secret and created_at > now() - interval '1 day') then return false; end if;
  if not exists (select 1 from public.players where code = p_inviter) then return false; end if;
  if exists (select 1 from public.referrals where invitee = p_invitee) then return false; end if;
  if not public._rate_ok('claim', 5, interval '1 day') then return false; end if;
  select count(*) into today_count from public.referrals where inviter = p_inviter and created_at > now() - interval '1 day';
  if today_count >= 10 then return false; end if;
  insert into public.referrals(inviter, invitee) values (p_inviter, p_invitee) on conflict (invitee) do nothing;
  return found;
end $$;

create or replace function public.collect_referral_rewards(p_code text, p_secret uuid) returns integer language plpgsql security definer set search_path to '' as $$
declare n int;
begin
  if not exists (select 1 from public.players where code = p_code and secret = p_secret) then return 0; end if;
  with c as (update public.referrals set claimed = true where inviter = p_code and not claimed returning 1)
  select count(*) into n from c;
  return n;
end $$;

-- Called only by the verify-purchase edge function (service role) after Google confirmed the purchase.
create or replace function public.record_purchase(p_token text, p_code text, p_secret uuid, p_product text, p_gems int, p_order text, p_test boolean) returns json language plpgsql security definer set search_path to '' as $$
declare owner text;
begin
  if not exists (select 1 from public.players where code = p_code and secret = p_secret) then
    return json_build_object('ok', false, 'error', 'bad_player');
  end if;
  insert into public.purchases(token, code, product, gems, order_id, test) values (p_token, p_code, p_product, p_gems, p_order, p_test)
    on conflict (token) do nothing;
  if found then return json_build_object('ok', true, 'first', true); end if;
  select code into owner from public.purchases where token = p_token;
  if owner = p_code then return json_build_object('ok', true, 'first', false); end if;
  return json_build_object('ok', false, 'error', 'token_used');
end $$;

revoke all on function public._caller_hash(), public._rate_ok(text, int, interval), public.record_purchase(text, text, uuid, text, int, text, boolean),
  public.register_player(text, uuid), public.claim_referral(text, uuid, text), public.collect_referral_rewards(text, uuid) from anon, authenticated, public;
grant execute on function public.register_player(text, uuid), public.claim_referral(text, uuid, text), public.collect_referral_rewards(text, uuid) to anon, authenticated;
grant execute on function public.record_purchase(text, text, uuid, text, int, text, boolean) to service_role;

-- =====================================================================
-- Backend-only access (added when the Cloudflare Worker backend went live).
-- The game no longer calls the database. Only the backend may, proving itself with a secret key whose
-- SHA-256 hash is stored in private.settings. The functions above stay for reference but are not callable
-- by anon/authenticated any more.
-- =====================================================================
create schema if not exists private;
revoke all on schema private from anon, authenticated, public;
create table if not exists private.settings (key text primary key, value text not null);
-- insert into private.settings values ('backend_key_sha256', '<sha256 hex of the backend key>');

create or replace function private.key_ok(p_key text) returns boolean language sql stable security definer set search_path to '' as $$
  select exists (select 1 from private.settings where key = 'backend_key_sha256'
                 and value = encode(sha256(convert_to(coalesce(p_key, ''), 'UTF8')), 'hex'));
$$;

create or replace function private.rate_ok(p_kind text, p_limit int, p_window interval, p_who text) returns boolean
language plpgsql volatile security definer set search_path to '' as $$
declare n int;
begin
  if random() < 0.02 then delete from public.rate_log where created_at < now() - interval '2 days'; end if;
  if p_who is null or p_who !~ '^[0-9a-f]{64}$' then return true; end if;
  select count(*) into n from public.rate_log where kind = p_kind and who = p_who and created_at > now() - p_window;
  if n >= p_limit then return false; end if;
  insert into public.rate_log(kind, who) values (p_kind, p_who);
  return true;
end $$;

create or replace function public.api_register(p_key text, p_who text, p_code text, p_secret uuid) returns boolean
language plpgsql security definer set search_path to '' as $$
declare existing uuid;
begin
  if not private.key_ok(p_key) then return null; end if;
  if p_code is null or p_code !~ '^[a-z0-9]{6}$' or p_secret is null then return false; end if;
  select secret into existing from public.players where code = p_code;
  if existing is null then
    if not private.rate_ok('register', 30, interval '1 hour', p_who) then return false; end if;
    if (select count(*) from public.players where created_at > now() - interval '10 minutes') >= 3000 then return false; end if;
    insert into public.players(code, secret) values (p_code, p_secret) on conflict (code) do nothing;
    select secret into existing from public.players where code = p_code;
  end if;
  return existing = p_secret;
end $$;

create or replace function public.api_claim(p_key text, p_who text, p_invitee text, p_secret uuid, p_inviter text) returns boolean
language plpgsql security definer set search_path to '' as $$
declare today_count int;
begin
  if not private.key_ok(p_key) then return null; end if;
  if p_inviter is null or p_invitee is null or p_inviter = p_invitee or p_inviter !~ '^[a-z0-9]{6}$' then return false; end if;
  if not exists (select 1 from public.players where code = p_invitee and secret = p_secret and created_at > now() - interval '1 day') then return false; end if;
  if not exists (select 1 from public.players where code = p_inviter) then return false; end if;
  if exists (select 1 from public.referrals where invitee = p_invitee) then return false; end if;
  if not private.rate_ok('claim', 5, interval '1 day', p_who) then return false; end if;
  select count(*) into today_count from public.referrals where inviter = p_inviter and created_at > now() - interval '1 day';
  if today_count >= 10 then return false; end if;
  insert into public.referrals(inviter, invitee) values (p_inviter, p_invitee) on conflict (invitee) do nothing;
  return found;
end $$;

create or replace function public.api_collect(p_key text, p_code text, p_secret uuid) returns integer
language plpgsql security definer set search_path to '' as $$
declare n int;
begin
  if not private.key_ok(p_key) then return null; end if;
  if not exists (select 1 from public.players where code = p_code and secret = p_secret) then return 0; end if;
  with c as (update public.referrals set claimed = true where inviter = p_code and not claimed returning 1)
  select count(*) into n from c;
  return n;
end $$;

create or replace function public.api_ping(p_key text) returns boolean language sql stable security definer set search_path to '' as $$
  select private.key_ok(p_key);
$$;

revoke all on function private.key_ok(text), private.rate_ok(text, int, interval, text) from anon, authenticated, public;
revoke execute on function public.register_player(text, uuid), public.claim_referral(text, uuid, text),
  public.collect_referral_rewards(text, uuid), public._caller_hash(), public._rate_ok(text, int, interval) from anon, authenticated, public;
revoke all on function public.api_register(text, text, text, uuid), public.api_claim(text, text, text, uuid, text),
  public.api_collect(text, text, uuid), public.api_ping(text) from public;
grant execute on function public.api_register(text, text, text, uuid), public.api_claim(text, text, text, uuid, text),
  public.api_collect(text, text, uuid), public.api_ping(text) to anon, authenticated;

-- =====================================================================
-- Server-side players (migration "server_players", 25 Nov 2026).
-- Adds to players: last_seen, sessions, app_version, country, age_group, device_hash (13+ only),
--   gems (server balance), owned (items and upgrade levels), progress (stars, medals, best scores),
--   levels_played, levels_cleared, best_level, transfer_hash, imported.
-- New table public.ledger: every gem movement, unique per (player, ref), so nothing is applied twice.
-- New table private.catalog: shop prices the server enforces (must match www/index.html).
-- New backend-only functions: api_session, api_import, api_sync, api_buy, api_claim (6 args),
--   api_collect (4 args), api_transfer_create, api_transfer_redeem; record_purchase now credits the wallet.
-- Rules: level result <= 1000 gems, run <= 3000, play earnings <= 8000/hour and 30000/day,
--   videos counted per UTC day, inviter paid only after the friend clears 5 levels, one welcome bonus per device.
-- The full SQL of every applied migration is kept in the project (supabase_migrations.schema_migrations);
-- `npx supabase db dump --schema public,private` writes the current schema to a file.
-- =====================================================================
