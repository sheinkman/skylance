// Skylance backend (Cloudflare Worker).
// The game talks only to this backend; only this backend talks to the database.
// Anything behind it (database provider, rules, rewards) can change without a game update.
//
// Secrets and settings (set as Worker bindings, never in this file):
//   BACKEND_KEY   secret: proves to the database that the call comes from this backend
//   SUPABASE_URL  plain:  https://<project>.supabase.co
//   SUPABASE_ANON plain:  the project's publishable key (public)

// Game settings the app downloads at launch. Change them here and redeploy: no app update needed.
const CONFIG = {
  version: 1,
  videoGems: 40,
  videosPerDay: 5,
  inviterGems: 200,
  inviteeGems: 150,
};

const CORS = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
  'Access-Control-Allow-Headers': 'content-type',
  'Access-Control-Max-Age': '86400',
};
const json = (status, body, extra = {}) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, 'Content-Type': 'application/json', 'Cache-Control': 'no-store', ...extra } });

const CODE = /^[a-z0-9]{6}$/;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

async function sha256hex(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

// The caller's network, as a one-way hash (same scheme as the database uses). The address itself is never stored.
async function who(req) {
  const ip = req.headers.get('CF-Connecting-IP');
  return ip ? sha256hex('skylance:' + ip) : null;
}

async function rpc(env, fn, args) {
  const r = await fetch(`${env.SUPABASE_URL}/rest/v1/rpc/${fn}`, {
    method: 'POST',
    headers: { apikey: env.SUPABASE_ANON, 'Content-Type': 'application/json' },
    body: JSON.stringify({ p_key: env.BACKEND_KEY, ...args }),
  });
  if (!r.ok) throw new Error(`db ${r.status}`);
  const v = await r.json();
  if (v === null) throw new Error('db refused the backend key');
  return v;
}

async function readBody(req) {
  if ((req.headers.get('content-length') | 0) > 4096) return null;
  try {
    const t = await req.text();
    if (t.length > 4096) return null;
    const b = JSON.parse(t);
    return b && typeof b === 'object' ? b : null;
  } catch {
    return null;
  }
}

async function handle(req, env) {
  const url = new URL(req.url);
  if (req.method === 'OPTIONS') return new Response(null, { headers: CORS });

  if (req.method === 'GET' && url.pathname === '/v1/config') return json(200, CONFIG, { 'Cache-Control': 'public, max-age=300' });
  if (req.method === 'GET' && url.pathname === '/v1/health') {
    const ok = await rpc(env, 'api_ping', {}).catch(() => false);
    return json(ok ? 200 : 503, { ok });
  }
  if (req.method !== 'POST') return json(404, { ok: false, error: 'not_found' });

  const b = await readBody(req);
  if (!b) return json(400, { ok: false, error: 'bad_json' });
  const code = String(b.code ?? ''), secret = String(b.secret ?? '');
  if (!CODE.test(code) || !UUID.test(secret)) return json(400, { ok: false, error: 'bad_input' });

  switch (url.pathname) {
    case '/v1/register': {
      const ok = await rpc(env, 'api_register', { p_who: await who(req), p_code: code, p_secret: secret });
      return json(200, { ok: ok === true });
    }
    case '/v1/invite/claim': {
      const inviter = String(b.inviter ?? '');
      if (!CODE.test(inviter)) return json(400, { ok: false, error: 'bad_input' });
      const ok = await rpc(env, 'api_claim', { p_who: await who(req), p_invitee: code, p_secret: secret, p_inviter: inviter });
      return json(200, { ok: ok === true, gems: ok === true ? CONFIG.inviteeGems : 0 });
    }
    case '/v1/invite/collect': {
      const n = Math.max(0, Math.min(50, (await rpc(env, 'api_collect', { p_code: code, p_secret: secret })) | 0));
      return json(200, { ok: true, count: n, gems: n * CONFIG.inviterGems });
    }
    case '/v1/purchase/verify': {
      const product = String(b.product ?? ''), token = String(b.token ?? '');
      if (!/^gems_\d{2,5}$/.test(product) || !/^[A-Za-z0-9._-]{20,600}$/.test(token)) return json(400, { ok: false, error: 'bad_input' });
      // The purchase check (which holds the Google key) runs as a Supabase function that accepts only this backend.
      const r = await fetch(`${env.SUPABASE_URL}/functions/v1/verify-purchase`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'x-backend-key': env.BACKEND_KEY },
        body: JSON.stringify({ code, secret, product, token }),
      });
      const text = await r.text();
      let out;
      try { out = JSON.parse(text); } catch { out = { ok: false, error: 'upstream' }; }
      return json(r.status, out);
    }
  }
  return json(404, { ok: false, error: 'not_found' });
}

export default {
  async fetch(req, env) {
    try {
      return await handle(req, env);
    } catch (e) {
      return json(502, { ok: false, error: 'server_unavailable' });
    }
  },
  // Cloudflare runs this on a schedule: one tiny database call so the free Supabase project never pauses.
  async scheduled(event, env, ctx) {
    ctx.waitUntil(rpc(env, 'api_ping', {}).catch(() => {}));
  },
};
