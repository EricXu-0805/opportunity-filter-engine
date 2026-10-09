/**
 * A loopback stand-in for Supabase, for E2E only.
 *
 * WHY THIS EXISTS
 * The E2E app used to be built with NEXT_PUBLIC_SUPABASE_URL empty. That was
 * fine while the UI flipped optimistically — a tracker pill turned on whether
 * or not anything persisted. It stopped being fine when the integrity work made
 * the UI follow persistence ("a failed write must never have been shown as
 * active even briefly", use-opportunity-detail.ts): with no storage backend at
 * all, tracker/favorites/dashboard behaviour is correctly inert, and every E2E
 * test that asserted the old optimistic behaviour became a test of nothing.
 *
 * Pointing the build at this loopback origin restores that coverage without a
 * hosted project: supabase-js is real, the HTTP is real, the app's auth and
 * write paths are real. Only the server is fake.
 *
 * WHAT IT IS NOT
 * Not PostgREST, and not a security boundary. It implements the operators this
 * app actually issues (eq filters, select, order/limit/range, insert, upsert
 * with on_conflict, update, delete, exact counts, the single-object Accept) and
 * nothing else. It deliberately does NOT enforce RLS — row ownership is proven
 * against real Postgres by supabase/tests/*.sql, and duplicating a weak version
 * of it here would only invite trusting the weak one.
 *
 * State is in memory and dies with the process. Every anonymous sign-in mints a
 * fresh uid, and Playwright starts each test from a storageState with no
 * session in it, so tests do not share rows.
 */
import { createServer } from 'node:http';
import { createHash, randomUUID } from 'node:crypto';
import { validStubTargetResumeProvenance } from './target-resume-provenance-stub.mjs';

const PORT = Number(process.env.E2E_SUPABASE_PORT ?? 54321);

/** table -> array of row objects */
const tables = new Map();
const rowsOf = (t) => {
  if (!tables.has(t)) tables.set(t, []);
  return tables.get(t);
};

// Composite keys the app upserts on, so `on_conflict` behaves like the real
// unique indexes rather than appending a duplicate row.
const CONFLICT_KEYS = {
  favorites: ['device_id', 'opportunity_id'],
  interactions: ['device_id', 'opportunity_id'],
  professor_follows: ['device_id', 'professor_id'],
  professor_update_reads: ['device_id', 'professor_id'],
  profiles: ['id'],
  saved_searches: ['id'],
  push_subscriptions: ['endpoint'],
};

const b64url = (obj) => Buffer.from(JSON.stringify(obj)).toString('base64url');

// ---------------------------------------------------------------------
// Accounts. A uid the stub never registered is an anonymous user, exactly as
// before. On top of that it keeps just enough of GoTrue's account model for
// the cloud-save scenarios: a permanent email account, an anonymous user
// converted in place by updateUser({ email }), a magic link into an existing
// account, and the PKCE exchange that finishes both. No mail leaves the
// process: every link lands in an in-memory outbox (GET /__e2e/outbox).
// ---------------------------------------------------------------------
/** uid -> { email, pendingEmail } ; email === null means anonymous. */
const accounts = new Map();
const outbox = [];
/** One-time link tokens and the PKCE codes they turn into. */
const linkTokens = new Map();
const authCodes = new Map();

const normalEmail = (value) => (typeof value === 'string' ? value.trim().toLowerCase() : '');
const accountOf = (uid) => accounts.get(uid) ?? { email: null, pendingEmail: null };
const uidForEmail = (email) => [...accounts].find(([, account]) => account.email === email)?.[0] ?? null;

/** A structurally real JWT. Nothing verifies the signature; supabase-js does
 *  read the payload, so `sub`/`exp`/`role` have to be there and be sane. The
 *  merge RPCs read `email` and `is_anonymous` from it, like auth.jwt() does. */
function mintToken(uid) {
  const now = Math.floor(Date.now() / 1000);
  const { email } = accountOf(uid);
  const payload = {
    sub: uid, aud: 'authenticated', role: 'authenticated',
    iat: now, exp: now + 3600, is_anonymous: email === null,
    ...(email === null ? {} : { email }),
  };
  return `${b64url({ alg: 'HS256', typ: 'JWT' })}.${b64url(payload)}.e2e-stub-signature`;
}

function userOf(uid) {
  const { email, pendingEmail } = accountOf(uid);
  const provider = email === null ? 'anonymous' : 'email';
  return {
    id: uid,
    aud: 'authenticated',
    role: 'authenticated',
    is_anonymous: email === null,
    email,
    ...(pendingEmail ? { new_email: pendingEmail } : {}),
    phone: null,
    app_metadata: { provider, providers: [provider] },
    user_metadata: {},
    identities: [],
    created_at: new Date(0).toISOString(),
    updated_at: new Date(0).toISOString(),
  };
}

function sessionFor(uid) {
  return {
    access_token: mintToken(uid),
    token_type: 'bearer',
    expires_in: 3600,
    expires_at: Math.floor(Date.now() / 1000) + 3600,
    refresh_token: `stub-refresh-${uid}`,
    user: userOf(uid),
  };
}

/** The claims a request is acting with, read from its bearer token. */
function callerClaims(req) {
  const auth = req.headers.authorization ?? '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    return JSON.parse(Buffer.from(part, 'base64url').toString());
  } catch { return null; }
}

/** The uid a request is acting as, read from its bearer token. */
function callerUid(req) {
  return callerClaims(req)?.sub ?? null;
}

/** GoTrue's error body: supabase-js reads `msg` and `error_code`. */
function authError(res, status, errorCode, msg) {
  return send(res, status, { code: status, error_code: errorCode, msg });
}

/** Queue the mail GoTrue would send: a /verify link carrying a one-time token
 *  bound to the account and to the requesting browser's PKCE challenge. */
function queueLink({ uid, email, type, body, redirectTo }) {
  const token = randomUUID();
  linkTokens.set(token, {
    uid, email, type, redirectTo,
    challenge: body.code_challenge ?? null, method: body.code_challenge_method ?? null,
  });
  const link = new URL(`http://127.0.0.1:${PORT}/auth/v1/verify`);
  link.searchParams.set('token', token);
  link.searchParams.set('type', type);
  if (redirectTo) link.searchParams.set('redirect_to', redirectTo);
  outbox.push({ email, type, link: link.href, sent_at: new Date().toISOString() });
}

function pkceMatches(grant, verifier) {
  if (!grant.challenge) return true;
  if (typeof verifier !== 'string' || !verifier) return false;
  if (grant.method === 'plain') return verifier === grant.challenge;
  return createHash('sha256').update(verifier).digest('base64url') === grant.challenge;
}

// ---------------------------------------------------------------------
// PostgREST-shaped querying — only the operators this app issues.
// ---------------------------------------------------------------------
function coerce(raw) {
  if (raw === 'null') return null;
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  return raw;
}

function applyFilters(rows, params) {
  let out = rows;
  for (const [key, value] of params) {
    if (['select', 'order', 'limit', 'offset', 'on_conflict', 'columns'].includes(key)) continue;
    const [op, ...rest] = value.split('.');
    const operand = rest.join('.');
    if (op === 'eq') out = out.filter((r) => String(r[key] ?? '') === String(coerce(operand) ?? ''));
    else if (op === 'neq') out = out.filter((r) => String(r[key] ?? '') !== String(coerce(operand) ?? ''));
    else if (op === 'is') out = out.filter((r) => (operand === 'null' ? r[key] == null : r[key] === coerce(operand)));
    else if (op === 'not') out = out.filter((r) => r[key] != null);
    else if (op === 'gte') out = out.filter((r) => r[key] >= operand);
    else if (op === 'lte') out = out.filter((r) => r[key] <= operand);
    else if (op === 'gt') out = out.filter((r) => r[key] > operand);
    else if (op === 'lt') out = out.filter((r) => r[key] < operand);
    else if (op === 'in') {
      const set = new Set(operand.replace(/^\(|\)$/g, '').split(',').map((s) => s.replace(/^"|"$/g, '')));
      out = out.filter((r) => set.has(String(r[key])));
    }
  }
  return out;
}

function applyOrder(rows, params) {
  const spec = params.get('order');
  if (!spec) return rows;
  const [col, dir = 'asc'] = spec.split('.');
  return [...rows].sort((a, b) => {
    const x = a[col], y = b[col];
    if (x === y) return 0;
    if (x == null) return 1;
    if (y == null) return -1;
    return (x < y ? -1 : 1) * (dir.startsWith('desc') ? -1 : 1);
  });
}

/** `select=a,b,c` — `*` and embedded resources are returned whole. */
function project(rows, params) {
  const sel = params.get('select');
  if (!sel || sel === '*' || sel.includes('(')) return rows;
  const cols = sel.split(',').map((c) => c.trim().split(':').pop());
  return rows.map((r) => Object.fromEntries(cols.filter((c) => c in r).map((c) => [c, r[c]])));
}

function conflictMatch(table, a, b) {
  const keys = CONFLICT_KEYS[table];
  if (!keys) return false;
  return keys.every((k) => String(a[k] ?? '') === String(b[k] ?? ''));
}

function send(res, status, body, extraHeaders = {}) {
  const payload = body === undefined ? '' : JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json',
    'access-control-allow-origin': '*',
    'access-control-allow-headers': '*',
    'access-control-expose-headers': 'content-range',
    'access-control-allow-methods': 'GET,POST,PATCH,DELETE,PUT,OPTIONS',
    ...extraHeaders,
  });
  res.end(payload);
}

/** `.maybeSingle()`/`.single()` ask for one object rather than an array. */
const wantsObject = (req) => (req.headers.accept ?? '').includes('pgrst.object');
const prefersRepresentation = (req) => (req.headers.prefer ?? '').includes('return=representation');
const wantsCount = (req) => (req.headers.prefer ?? '').includes('count=exact');

function respondRows(req, res, rows, params, total) {
  const projected = project(rows, params);
  const headers = wantsCount(req)
    ? { 'content-range': `0-${Math.max(projected.length - 1, 0)}/${total ?? projected.length}` }
    : {};
  if (wantsObject(req)) return send(res, 200, projected[0] ?? null, headers);
  send(res, 200, projected, headers);
}

// ---------------------------------------------------------------------
// RPCs. Each mirrors the migration it stands in for closely enough that the
// CLIENT sees the same contract; the SQL itself is tested against real
// Postgres in supabase/tests/.
// ---------------------------------------------------------------------
function canonicalJSON(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalJSON).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(k => `${JSON.stringify(k)}:${canonicalJSON(value[k])}`).join(',')}}`;
  return JSON.stringify(value);
}
function renovationError(message = 'invalid_renovation') {
  return { status: 400, body: { code: '22023', message } };
}
function renovationOwner(body, uid) {
  if (!uid || body.p_expected_owner !== uid || rowsOf('merged_devices').some(row => row.source_device_id === uid)) {
    return { status: 403, body: { code: '42501', message: 'identity_changed' } };
  }
  if (typeof body.p_opportunity_id !== 'string' || !body.p_opportunity_id.trim()
    || Array.from(body.p_opportunity_id).length > 200) return renovationError();
  return null;
}
function renovationCurrent(row) {
  return { owner_id: row.owner_id, opportunity_id: row.opportunity_id, revision: row.revision,
    updated_at: row.updated_at, payload: structuredClone(row.payload) };
}
function renovationSummary(row) {
  return { id: row.id, created_at: row.created_at, revision: row.revision,
    snapshot_kind: row.snapshot_kind, source_revision: row.source_revision, source_updated_at: row.source_updated_at };
}
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const rpcs = {
  // Legacy bullet drafts now use bounded RPCs. The old table REST endpoints
  // remain closed below; this is client-wire fidelity, not a replacement for
  // the real PostgreSQL ACL/transaction/concurrency tests.
  read_renovation(body, uid) {
    const invalid = renovationOwner(body, uid); if (invalid) return invalid;
    const row = rowsOf('resume_renovations').find(row => row.owner_id === uid && row.opportunity_id === body.p_opportunity_id);
    return { status: 200, body: row ? { status: 'found', current: renovationCurrent(row) } : { status: 'absent' } };
  },
  save_renovation_cas(body, uid) {
    const invalid = renovationOwner(body, uid); if (invalid) return invalid;
    const expected = body.p_expected_revision, payload = body.p_payload, opp = body.p_opportunity_id;
    if (!Number.isSafeInteger(expected) || expected < 0 || !record(payload)
      || Object.keys(payload).sort().join(',') !== 'base_snapshot,doc,method,warnings'
      || !record(payload.doc) || payload.doc.kind === 'full_resume' || !Array.isArray(payload.doc.sections) || !record(payload.base_snapshot)
      || (payload.method !== null && typeof payload.method !== 'string')
      || !Array.isArray(payload.warnings) || !payload.warnings.every(item => typeof item === 'string')
      || Buffer.byteLength(JSON.stringify(payload), 'utf8') > 2 * 1024 * 1024) return renovationError();
    const rows = rowsOf('resume_renovations');
    const row = rows.find(row => row.owner_id === uid && row.opportunity_id === opp);
    if (!row && expected !== 0) return { status: 200, body: { status: 'missing' } };
    const respond = (status, value) => ({ status: 200, body: { status, current: renovationCurrent(value) } });
    if (row && canonicalJSON(row.payload) === canonicalJSON(payload) && [expected, expected + 1].includes(row.revision)) return respond('unchanged', row);
    if (row && expected !== row.revision) return respond('conflict', row);
    if (row && row.revision >= Number.MAX_SAFE_INTEGER) return renovationError('revision_limit');
    const now = new Date().toISOString();
    const next = { owner_id: uid, opportunity_id: opp, revision: (row?.revision ?? 0) + 1,
      updated_at: now, payload: structuredClone(payload) };
    if (row) Object.assign(row, next); else rows.push(next);
    rowsOf('resume_renovation_versions').push({ ...structuredClone(next), id: randomUUID(), created_at: now,
      snapshot_kind: 'complete', source_revision: null, source_updated_at: null });
    return respond('saved', next);
  },
  list_renovation_versions(body, uid) {
    const invalid = renovationOwner(body, uid); if (invalid) return invalid;
    const before = body.p_before_created_at ?? null, beforeId = body.p_before_id ?? null, limit = body.p_limit === undefined ? 20 : body.p_limit;
    if (!Number.isSafeInteger(limit) || limit < 1 || limit > 50 || (before === null) !== (beforeId === null)
      || (before !== null && (typeof before !== 'string' || !Number.isFinite(Date.parse(before))
        || typeof beforeId !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(beforeId)))) return renovationError('invalid_cursor');
    const sorted = rowsOf('resume_renovation_versions').filter(row => row.owner_id === uid && row.opportunity_id === body.p_opportunity_id)
      .filter(row => before === null || Date.parse(row.created_at) < Date.parse(before)
        || (Date.parse(row.created_at) === Date.parse(before) && row.id < beforeId))
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || (a.id < b.id ? 1 : a.id > b.id ? -1 : 0));
    const selected = sorted.slice(0, limit), last = selected.at(-1);
    return { status: 200, body: { items: selected.map(renovationSummary),
      next_cursor: sorted.length > limit && last ? { created_at: last.created_at, id: last.id } : null } };
  },
  get_renovation_version(body, uid) {
    const invalid = renovationOwner(body, uid); if (invalid) return invalid;
    if (typeof body.p_version_id !== 'string' || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(body.p_version_id)) return renovationError();
    const row = rowsOf('resume_renovation_versions').find(row => row.owner_id === uid
      && row.opportunity_id === body.p_opportunity_id && row.id === body.p_version_id);
    return { status: 200, body: row ? { status: 'found', version: { ...renovationSummary(row), owner_id: uid,
      opportunity_id: row.opportunity_id, payload: structuredClone(row.payload) } } : { status: 'absent' } };
  },
  // Independent full-document CAS. Real RLS/merge/rollback is proven in SQL;
  // the stub reproduces only this wire contract for local browser tests.
  commit_target_resume_with_provenance_cas(body, uid) {
    return rpcs.commit_target_resume_cas(body, uid, null, true);
  },
  commit_target_resume_cas(body, uid, _claims, withProvenance = false) {
    const { p_expected_owner: owner, p_opportunity_id: opp, p_expected_revision: expected, p_doc: doc } = body;
    if (!uid || owner !== uid) return { status: 403, body: { code: '42501', message: 'identity_changed' } };
    if (!Number.isSafeInteger(expected) || expected < 0 || typeof opp !== 'string' || !opp.trim()
      || Array.from(opp).length > 200 || !doc || doc.kind !== 'full_resume' || doc.version !== 1
      || doc.opportunity_id !== opp || !doc.base || !doc.base_snapshot || !doc.target_snapshot
      || !Array.isArray(doc.document?.sections) || Buffer.byteLength(JSON.stringify(doc), 'utf8') > 2097152) {
      return { status: 400, body: { code: '22023', message: 'invalid_target_resume' } };
    }
    if (rowsOf('merged_devices').some(row => row.source_device_id === uid)) return { status: 200, body: { status: 'missing' } };
    const provenance = withProvenance ? body.p_provenance ?? null : null;
    if (!validStubTargetResumeProvenance(doc, provenance)) {
      return { status: 400, body: { code: '22023', message: 'invalid_target_resume_provenance' } };
    }
    const current = rowsOf('target_resumes');
    const row = current.find(r => r.owner_id === uid && r.opportunity_id === opp);
    if (!row && expected !== 0) return { status: 200, body: { status: 'missing' } };
    const response = (status, value) => ({ status: 200, body: { status, revision: value.revision, doc: value.doc, ...(withProvenance ? { provenance: value.provenance ?? null } : {}), updated_at: value.updated_at } });
    if (row && canonicalJSON(row.doc) === canonicalJSON(doc)
      && (!withProvenance || canonicalJSON(row.provenance ?? null) === canonicalJSON(provenance)) && [expected, expected + 1].includes(row.revision)) return response('unchanged', row);
    if (row && row.revision !== expected) return response('conflict', row);
    if (row && row.revision >= Number.MAX_SAFE_INTEGER) return { status: 400, body: { code: '22023', message: 'revision_limit' } };
    const next = { owner_id: uid, opportunity_id: opp, revision: (row?.revision ?? 0) + 1,
      doc: structuredClone(doc), provenance: structuredClone(provenance), updated_at: new Date().toISOString() };
    if (row) Object.assign(row, next); else current.push(next);
    rowsOf('target_resume_versions').push(structuredClone(next));
    return response('saved', next);
  },
  // supabase/migrations/027_confirm_interaction_contact.sql
  confirm_interaction_contact(body, uid) {
    const { p_expected_device_id: expected, p_opportunity_id: oppId, p_remind_at: remindAt } = body;
    if (expected == null || uid !== expected) {
      return { status: 403, body: { message: 'identity_changed', code: '42501' } };
    }
    if (oppId == null || String(oppId).trim() === '') {
      return { status: 400, body: { message: 'invalid_opportunity', code: '22023' } };
    }
    const rows = rowsOf('interactions');
    const now = new Date().toISOString();
    let row = rows.find((r) => r.device_id === expected && r.opportunity_id === oppId);
    if (!row) {
      row = {
        device_id: expected,
        opportunity_id: oppId,
        // 'contacted', mirroring 027: a confirmed send is outreach, not an application.
        interaction_type: 'contacted',
        notes: null,
        remind_at: remindAt ?? null,
        last_contacted_at: now,
        created_at: now,
        updated_at: now,
      };
      rows.push(row);
    } else {
      // Never touches interaction_type or notes: an already-advanced status
      // and any notes survive byte for byte.
      row.last_contacted_at = now;
      row.remind_at = remindAt ?? row.remind_at ?? null;
      row.updated_at = now;
    }
    return { status: 200, body: [row] };
  },

  // supabase/migrations/029_profile_save_cas.sql — compare-and-set on
  // revision. RETURNS jsonb: one envelope object, NOT an array of rows —
  // PostgREST serialises a scalar-jsonb function result as the value itself,
  // and src/lib/supabase.ts reads `data.status` straight off it (an earlier
  // hand-invented [{applied, conflict}] shape parsed as `status: undefined`
  // -> 'malformed' -> device-failed -> Generate refused to navigate, which
  // took out every goToResults e2e). Field names and branch conditions below
  // mirror 027 line for line; the real semantics are proven against Postgres
  // by supabase/tests, this stub only has to speak the same wire shape.
  commit_profile_patch_cas(body, uid) {
    const expected = body.p_expected_device_id;
    if (!uid || expected == null || expected !== uid) {
      return { status: 403, body: { message: 'identity_changed', code: '42501' } };
    }
    const patch = body.p_patch;
    if (!patch || typeof patch !== 'object' || Object.keys(patch).length === 0) {
      return { status: 400, body: { message: 'empty_patch', code: '22023' } };
    }
    const expectedRevision = Number(body.p_expected_revision ?? 0);
    // An account merged into another one owns no profile any more (029).
    if (rowsOf('merged_devices').some((r) => r.source_device_id === uid)) {
      return {
        status: 200,
        body: { status: 'missing', reason: 'merged_away', revision: 0, profile: null, updated_at: null },
      };
    }
    const rows = rowsOf('profiles');
    const now = new Date().toISOString();
    let row = rows.find((r) => r.id === uid);

    if (!row) {
      if (expectedRevision !== 0) {
        return {
          status: 200,
          body: { status: 'missing', reason: 'absent', revision: 0, profile: null, updated_at: null },
        };
      }
      row = { id: uid, profile_data: { ...patch }, revision: 1, created_at: now, updated_at: now };
      rows.push(row);
      return {
        status: 200,
        body: { status: 'applied', revision: 1, profile: row.profile_data, updated_at: now },
      };
    }

    const merged = { ...row.profile_data, ...patch };
    const unchanged = JSON.stringify(merged) === JSON.stringify(row.profile_data);
    if (unchanged && (row.revision === expectedRevision || row.revision === expectedRevision + 1)) {
      return {
        status: 200,
        body: { status: 'unchanged', revision: row.revision, profile: row.profile_data, updated_at: row.updated_at },
      };
    }
    if (row.revision !== expectedRevision) {
      return {
        status: 200,
        body: { status: 'conflict', revision: row.revision, profile: row.profile_data, updated_at: row.updated_at },
      };
    }
    row.profile_data = merged;
    row.revision += 1;
    row.updated_at = now;
    return {
      status: 200,
      body: { status: 'applied', revision: row.revision, profile: row.profile_data, updated_at: now },
    };
  },

  // supabase/migrations/025 (mint_merge_grant) — RETURNS uuid, which PostgREST
  // serialises as a bare JSON string; supabase.ts drops anything else.
  mint_merge_grant(body, uid, claims) {
    if (!uid) return raise('mint_merge_grant: no authenticated session');
    if (claims?.is_anonymous !== true) {
      return raise('mint_merge_grant: only an anonymous session may mint a merge grant');
    }
    const email = normalEmail(body.p_target_email) || null;
    const secretHash = typeof body.p_secret_hash === 'string' && body.p_secret_hash.trim() ? body.p_secret_hash.trim() : null;
    if (email !== null && secretHash !== null) {
      return raise('mint_merge_grant: provide exactly one binding (target email or secret hash), not both');
    }
    if (email === null && secretHash === null) return raise('mint_merge_grant: target email is required');
    if (rowsOf('merged_devices').some((r) => r.source_device_id === uid)) {
      return raise('mint_merge_grant: device already merged');
    }
    const token = randomUUID();
    rowsOf('merge_grants').push({
      token, source_device_id: uid, target_email: email, secret_hash: secretHash,
      expires_at: Date.now() + 60 * 60 * 1000, consumed_at: null, redeemed_by: null, redeemed_result: null,
    });
    return { status: 200, body: token };
  },

  // supabase/migrations/034 (redeem_merge_grant, the current body): the
  // email/secret binding, idempotent replay, both tombstone guards, and the
  // per-table rules for the tables this stub holds. The whole body — including
  // the notes salvage and the tables not modelled here (orders, renovations,
  // waitlist, attachments) — runs against real Postgres in
  // supabase/tests/run_flow_b_test.sh.
  redeem_merge_grant(body, uid, claims) {
    if (!uid) return raise('redeem_merge_grant: no authenticated session');
    const grant = rowsOf('merge_grants').find((g) => g.token === body.p_token);
    if (!grant) return raise('redeem_merge_grant: invalid grant');
    const secret = typeof body.p_secret === 'string' ? body.p_secret : null;
    const boundOk = grant.secret_hash !== null
      ? secret !== null && createHash('sha256').update(secret, 'utf8').digest('hex') === grant.secret_hash
      : grant.target_email !== null && grant.target_email === normalEmail(claims?.email);
    if (grant.consumed_at !== null) {
      if (grant.redeemed_by === uid && boundOk) return { status: 200, body: grant.redeemed_result };
      return raise('redeem_merge_grant: grant already used');
    }
    if (grant.expires_at < Date.now()) return raise('redeem_merge_grant: grant expired');
    if (grant.target_email === null && grant.secret_hash === null) {
      return raise('redeem_merge_grant: unbound grant is not redeemable');
    }
    if (!boundOk) {
      return raise(`redeem_merge_grant: grant not bound to this ${grant.secret_hash !== null ? 'session' : 'account'}`);
    }
    const source = grant.source_device_id;
    const consume = (result) => {
      Object.assign(grant, { consumed_at: new Date().toISOString(), redeemed_by: uid, redeemed_result: result });
      return { status: 200, body: result };
    };
    if (source === uid) return consume({ merged: false, reason: 'same_device' });
    const tombstones = rowsOf('merged_devices');
    if (tombstones.some((r) => r.source_device_id === source)) {
      return consume({ merged: false, reason: 'source_already_merged' });
    }
    if (tombstones.some((r) => r.source_device_id === uid)) return raise('redeem_merge_grant: target already merged');

    const summary = { favorites: moveDeviceRows('favorites', 'opportunity_id', source, uid) };
    // interactions: last writer wins per opportunity (by updated_at).
    const stamp = (row) => Date.parse(row.updated_at ?? '') || -Infinity;
    const newer = new Set(rowsOf('interactions').filter((s) => s.device_id === source)
      .flatMap((s) => rowsOf('interactions').filter((t) => t.device_id === uid
        && t.opportunity_id === s.opportunity_id && stamp(s) > stamp(t))));
    tables.set('interactions', rowsOf('interactions').filter((t) => !newer.has(t)));
    summary.interactions = moveDeviceRows('interactions', 'opportunity_id', source, uid);
    // profiles: keep the target's; adopt the source's only when the target has
    // none; otherwise keep the source's as a revision-less profile_version.
    const profiles = rowsOf('profiles');
    const sourceProfile = profiles.find((r) => r.id === source);
    if (!profiles.some((r) => r.id === uid)) {
      if (sourceProfile) sourceProfile.id = uid;
      summary.profile = sourceProfile ? 'adopted' : 'none';
    } else if (sourceProfile) {
      rowsOf('profile_versions').push({
        device_id: uid, profile_data: structuredClone(sourceProfile.profile_data),
        created_at: new Date().toISOString(), profile_revision: null,
      });
      tables.set('profiles', profiles.filter((r) => r !== sourceProfile));
      summary.profile = 'kept_target_saved_other_as_version';
    } else {
      summary.profile = 'kept_target';
    }
    summary.saved_searches = moveDeviceRows('saved_searches', 'id', source, uid);
    summary.professor_follows = moveDeviceRows('professor_follows', 'professor_id', source, uid);
    moveDeviceRows('professor_update_reads', 'professor_id', source, uid);
    summary.attachments_not_moved = 0;
    const result = { merged: true, summary };
    tombstones.push({ source_device_id: source, target_device_id: uid, summary });
    return consume(result);
  },
};

/** RAISE EXCEPTION as PostgREST reports it: HTTP 400, SQLSTATE P0001. */
function raise(message) {
  return { status: 400, body: { code: 'P0001', message, details: null, hint: null } };
}

/** Re-key `source`'s rows of `table` to `target`. Where both hold a row with
 *  the same `key`, the target's stays and the source's is dropped (034's
 *  set-union rule). Returns how many rows moved. */
function moveDeviceRows(table, key, source, target) {
  const held = new Set(rowsOf(table).filter((r) => r.device_id === target).map((r) => String(r[key])));
  const kept = rowsOf(table).filter((r) => r.device_id !== source || !held.has(String(r[key])));
  let moved = 0;
  for (const row of kept) if (row.device_id === source) { row.device_id = target; moved += 1; }
  tables.set(table, kept);
  return moved;
}

// ---------------------------------------------------------------------
const server = createServer((req, res) => {
  if (req.method === 'OPTIONS') return send(res, 204);

  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  const path = url.pathname;
  if (path === '/health') return send(res, 200, { status: 'ok', stub: 'supabase' });

  const chunks = [];
  req.on('data', (c) => chunks.push(c));
  req.on('end', () => {
    const raw = Buffer.concat(chunks).toString();
    let body = {};
    if (raw) { try { body = JSON.parse(raw); } catch { body = {}; } }

    // ---------------- auth ----------------
    if (path.startsWith('/auth/v1/')) {
      const op = path.slice('/auth/v1/'.length);
      const redirectTo = url.searchParams.get('redirect_to');
      if (op === 'signup') {
        const uid = randomUUID();
        const email = normalEmail(body.email);
        // An email signup is a confirmed permanent account (autoconfirm on).
        if (email) {
          if (uidForEmail(email)) return authError(res, 422, 'user_already_exists', 'User already registered');
          accounts.set(uid, { email, pendingEmail: null });
        }
        return send(res, 200, sessionFor(uid));
      }
      if (op === 'token' && url.searchParams.get('grant_type') === 'pkce') {
        const grant = authCodes.get(String(body.auth_code ?? ''));
        if (!grant) return authError(res, 404, 'flow_state_not_found', 'invalid flow state, no valid flow state found');
        if (!pkceMatches(grant, body.code_verifier)) {
          return authError(res, 403, 'bad_code_verifier', 'code challenge does not match previously saved code verifier');
        }
        authCodes.delete(String(body.auth_code));
        return send(res, 200, sessionFor(grant.uid));
      }
      if (op === 'token') {
        const uid = callerUid(req)
          ?? String(body.refresh_token ?? '').replace('stub-refresh-', '')
          ?? randomUUID();
        return send(res, 200, sessionFor(uid || randomUUID()));
      }
      if (op === 'logout') return send(res, 204);
      if (op === 'user' && req.method === 'PUT') {
        const uid = callerUid(req);
        if (!uid) return send(res, 401, { message: 'invalid claim: missing sub' });
        const email = normalEmail(body.email);
        if (email) {
          const owner = uidForEmail(email);
          if (owner && owner !== uid) {
            return authError(res, 422, 'email_exists', 'A user with this email address has already been registered');
          }
          accounts.set(uid, { ...accountOf(uid), pendingEmail: email });
          queueLink({ uid, email, type: 'email_change', body, redirectTo });
        }
        return send(res, 200, userOf(uid));
      }
      if (op === 'user') {
        const uid = callerUid(req);
        if (!uid) return send(res, 401, { message: 'invalid claim: missing sub' });
        return send(res, 200, userOf(uid));
      }
      if (op === 'otp') {
        const email = normalEmail(body.email);
        if (!email) return authError(res, 422, 'validation_failed', 'Unable to validate email address: invalid format');
        let uid = uidForEmail(email);
        if (!uid) {
          if (body.create_user === false) return authError(res, 422, 'otp_disabled', 'Signups not allowed for otp');
          uid = randomUUID();
          accounts.set(uid, { email, pendingEmail: null });
        }
        queueLink({ uid, email, type: 'magiclink', body, redirectTo });
        return send(res, 200, {});
      }
      if (op === 'verify' && req.method === 'GET') {
        // The link in the mail: spend the one-time token, then hand the
        // browser back to the app with a PKCE code, as GoTrue does.
        const token = url.searchParams.get('token') ?? '';
        const pending = linkTokens.get(token);
        linkTokens.delete(token);
        const target = redirectTo ?? pending?.redirectTo;
        if (!target) return authError(res, 400, 'validation_failed', 'redirect_to is required');
        if (!pending) {
          res.writeHead(303, { location: `${target}#error=access_denied&error_code=otp_expired&error_description=Email+link+is+invalid+or+has+expired` });
          return res.end();
        }
        if (pending.type === 'email_change') {
          // GoTrue confirms the change while verifying the link, before any
          // code is exchanged (internal/api/verify.go, emailChangeVerify). The
          // anonymous user becomes permanent IN PLACE: same uid, same rows.
          accounts.set(pending.uid, { email: pending.email, pendingEmail: null });
        }
        const code = randomUUID();
        authCodes.set(code, pending);
        const next = new URL(target);
        next.searchParams.set('code', code);
        res.writeHead(303, { location: next.href });
        return res.end();
      }
      // authorize (OAuth): the E2E build runs with NEXT_PUBLIC_AUTH_PROVIDERS
      // empty, so nothing here is exercised. Answer plausibly rather than 404
      // into a confusing UI.
      return send(res, 200, {});
    }

    // ---------------- mail (test-only) ----------------
    // What GoTrue would have emailed, oldest first, so a spec can open the link
    // the way a student opens it from their inbox.
    if (path === '/__e2e/outbox') {
      const email = normalEmail(url.searchParams.get('email'));
      return send(res, 200, outbox.filter((mail) => !email || mail.email === email));
    }

    // ---------------- rest ----------------
    if (path.startsWith('/rest/v1/rpc/')) {
      const name = path.slice('/rest/v1/rpc/'.length);
      const fn = rpcs[name];
      if (!fn) return send(res, 404, { message: `stub: unimplemented rpc ${name}`, code: '42883' });
      const out = fn(body, callerUid(req), callerClaims(req));
      return send(res, out.status, out.body);
    }

    if (path.startsWith('/rest/v1/')) {
      const table = path.slice('/rest/v1/'.length).split('/')[0];
      if (!table) return send(res, 404, { message: 'stub: no table' });
      if (['resume_renovations', 'resume_renovation_versions'].includes(table)) {
        return send(res, 403, { code: '42501', message: 'permission denied for legacy renovation table' });
      }
      const rows = rowsOf(table);
      const params = url.searchParams;

      if (req.method === 'GET' || req.method === 'HEAD') {
        let matched = applyOrder(applyFilters(rows, params), params);
        const total = matched.length;
        const range = req.headers.range;
        if (range) {
          const [from, to] = range.split('-').map(Number);
          matched = matched.slice(from, Number.isFinite(to) ? to + 1 : undefined);
        }
        const limit = Number(params.get('limit'));
        if (Number.isFinite(limit) && limit > 0) matched = matched.slice(0, limit);
        if (req.method === 'HEAD') {
          return send(res, 200, undefined, wantsCount(req)
            ? { 'content-range': `0-${Math.max(total - 1, 0)}/${total}` } : {});
        }
        return respondRows(req, res, matched, params, total);
      }

      if (req.method === 'POST') {
        const incoming = Array.isArray(body) ? body : [body];
        const isUpsert = (req.headers.prefer ?? '').includes('merge-duplicates');
        const written = [];
        for (const item of incoming) {
          const existing = isUpsert ? rows.find((r) => conflictMatch(table, r, item)) : undefined;
          if (existing) {
            Object.assign(existing, item);
            written.push(existing);
          } else {
            const row = { id: item.id ?? randomUUID(), created_at: new Date().toISOString(), ...item };
            rows.push(row);
            written.push(row);
          }
        }
        if (!prefersRepresentation(req)) return send(res, 201, null);
        return respondRows(req, res, written, params, written.length);
      }

      if (req.method === 'PATCH') {
        const matched = applyFilters(rows, params);
        for (const row of matched) Object.assign(row, body);
        if (!prefersRepresentation(req)) return send(res, 204);
        return respondRows(req, res, matched, params, matched.length);
      }

      if (req.method === 'DELETE') {
        const doomed = new Set(applyFilters(rows, params));
        const kept = rows.filter((r) => !doomed.has(r));
        tables.set(table, kept);
        if (!prefersRepresentation(req)) return send(res, 204);
        return respondRows(req, res, [...doomed], params, doomed.size);
      }
    }

    send(res, 404, { message: `stub: unhandled ${req.method} ${path}` });
  });
});

server.listen(PORT, '127.0.0.1', () => {
  process.stdout.write(`[supabase-stub] listening on http://127.0.0.1:${PORT}\n`);
});
