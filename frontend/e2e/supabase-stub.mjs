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
import { randomUUID } from 'node:crypto';

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

/** A structurally real JWT. Nothing verifies the signature; supabase-js does
 *  read the payload, so `sub`/`exp`/`role` have to be there and be sane. */
function mintToken(uid) {
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    sub: uid, aud: 'authenticated', role: 'authenticated',
    iat: now, exp: now + 3600, is_anonymous: true,
  };
  return `${b64url({ alg: 'HS256', typ: 'JWT' })}.${b64url(payload)}.e2e-stub-signature`;
}

function userOf(uid) {
  return {
    id: uid,
    aud: 'authenticated',
    role: 'authenticated',
    is_anonymous: true,
    email: null,
    phone: null,
    app_metadata: { provider: 'anonymous', providers: ['anonymous'] },
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

/** The uid a request is acting as, read from its bearer token. */
function callerUid(req) {
  const auth = req.headers.authorization ?? '';
  const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
  const part = token.split('.')[1];
  if (!part) return null;
  try {
    return JSON.parse(Buffer.from(part, 'base64url').toString()).sub ?? null;
  } catch { return null; }
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
const rpcs = {
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
        interaction_type: 'applied',
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

  // supabase/migrations/017 + 026 — a grant is minted, never redeemed here.
  mint_merge_grant(body, uid) {
    if (!uid) return { status: 403, body: { message: 'identity_changed', code: '42501' } };
    return { status: 200, body: [{ token: `stub-grant-${randomUUID()}`, expires_at: new Date(Date.now() + 6e5).toISOString() }] };
  },
};

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
      if (op === 'signup') return send(res, 200, sessionFor(randomUUID()));
      if (op === 'token') {
        const uid = callerUid(req)
          ?? String(body.refresh_token ?? '').replace('stub-refresh-', '')
          ?? randomUUID();
        return send(res, 200, sessionFor(uid || randomUUID()));
      }
      if (op === 'logout') return send(res, 204);
      if (op === 'user') {
        const uid = callerUid(req);
        if (!uid) return send(res, 401, { message: 'invalid claim: missing sub' });
        return send(res, 200, userOf(uid));
      }
      // otp / verify / authorize: the E2E build runs with
      // NEXT_PUBLIC_AUTH_PROVIDERS empty and dev-echo email, so nothing here
      // is exercised. Answer plausibly rather than 404 into a confusing UI.
      return send(res, 200, {});
    }

    // ---------------- rest ----------------
    if (path.startsWith('/rest/v1/rpc/')) {
      const name = path.slice('/rest/v1/rpc/'.length);
      const fn = rpcs[name];
      if (!fn) return send(res, 404, { message: `stub: unimplemented rpc ${name}`, code: '42883' });
      const out = fn(body, callerUid(req));
      return send(res, out.status, out.body);
    }

    if (path.startsWith('/rest/v1/')) {
      const table = path.slice('/rest/v1/'.length).split('/')[0];
      if (!table) return send(res, 404, { message: 'stub: no table' });
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
