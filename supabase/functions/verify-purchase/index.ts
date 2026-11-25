// Verifies a Google Play gem purchase before the game grants gems.
// Flow: game sends {code, secret, product, token} -> this function asks Google whether the purchase is real
// -> records the token once in the purchases table -> replies with the gems to add. The game then consumes the purchase.
// Needs the secret GOOGLE_PLAY_SERVICE_ACCOUNT (the JSON key of a service account linked in Play Console).
// Only the Skylance backend may call it: it sends its key in x-backend-key, which the database checks.

const PACKAGE = "com.skylance.game";
const PACKS: Record<string, number> = { gems_300: 300, gems_1000: 1000, gems_2200: 2200, gems_5000: 5000 };
const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "apikey, content-type, authorization, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
};
const reply = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { ...CORS, "Content-Type": "application/json" } });

const b64url = (data: ArrayBuffer | string) =>
  btoa(typeof data === "string" ? data : String.fromCharCode(...new Uint8Array(data)))
    .replace(/=+$/, "").replace(/\+/g, "-").replace(/\//g, "_");

let cachedToken: { value: string; exp: number } | null = null;

async function googleAccessToken(sa: { client_email: string; private_key: string }): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  if (cachedToken && cachedToken.exp > now + 60) return cachedToken.value;
  const header = b64url(JSON.stringify({ alg: "RS256", typ: "JWT" }));
  const claims = b64url(JSON.stringify({
    iss: sa.client_email,
    scope: "https://www.googleapis.com/auth/androidpublisher",
    aud: "https://oauth2.googleapis.com/token",
    iat: now,
    exp: now + 3600,
  }));
  const pem = sa.private_key.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(pem), (c) => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${header}.${claims}`));
  const res = await fetch("https://oauth2.googleapis.com/token", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      grant_type: "urn:ietf:params:oauth:grant-type:jwt-bearer",
      assertion: `${header}.${claims}.${b64url(sig)}`,
    }),
  });
  if (!res.ok) throw new Error("google_auth_failed");
  const j = await res.json();
  cachedToken = { value: j.access_token, exp: now + (j.expires_in || 3600) };
  return cachedToken.value;
}

async function rest(path: string, init: RequestInit = {}) {
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!;
  return fetch(`${Deno.env.get("SUPABASE_URL")}/rest/v1/${path}`, {
    ...init,
    headers: { apikey: key, Authorization: `Bearer ${key}`, "Content-Type": "application/json", ...(init.headers || {}) },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS });
  if (req.method !== "POST") return reply(405, { ok: false, error: "method" });

  const backendKey = req.headers.get("x-backend-key") ?? "";
  const kr = backendKey ? await rest("rpc/api_ping", { method: "POST", body: JSON.stringify({ p_key: backendKey }) }) : null;
  if (!kr || !kr.ok || (await kr.json()) !== true) return reply(403, { ok: false, error: "backend_only" });

  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return reply(400, { ok: false, error: "bad_json" }); }
  const code = String(body.code ?? ""), secret = String(body.secret ?? "");
  const product = String(body.product ?? ""), token = String(body.token ?? "");
  if (!/^[a-z0-9]{6}$/.test(code) || !/^[0-9a-f-]{36}$/i.test(secret) || !(product in PACKS) || !/^[A-Za-z0-9._-]{20,600}$/.test(token)) {
    return reply(400, { ok: false, error: "bad_input" });
  }

  // Cheap check first, so junk requests never reach Google.
  const pr = await rest(`players?select=code&code=eq.${code}&secret=eq.${secret}`);
  if (!pr.ok || (await pr.json()).length !== 1) return reply(403, { ok: false, error: "bad_player" });

  const saRaw = Deno.env.get("GOOGLE_PLAY_SERVICE_ACCOUNT");
  if (!saRaw) return reply(503, { ok: false, error: "not_configured" });

  let p: Record<string, unknown>;
  try {
    const at = await googleAccessToken(JSON.parse(saRaw));
    const gr = await fetch(
      `https://androidpublisher.googleapis.com/androidpublisher/v3/applications/${PACKAGE}/purchases/products/${product}/tokens/${encodeURIComponent(token)}`,
      { headers: { Authorization: `Bearer ${at}` } },
    );
    if (gr.status === 404 || gr.status === 400 || gr.status === 410) return reply(402, { ok: false, error: "not_a_purchase" });
    if (!gr.ok) return reply(502, { ok: false, error: "google_error" });
    p = await gr.json();
  } catch {
    return reply(502, { ok: false, error: "google_error" });
  }

  // purchaseState: 0 purchased, 1 cancelled, 2 pending.
  if (p.purchaseState === 2) return reply(202, { ok: false, error: "pending" });
  if (p.purchaseState !== 0) return reply(402, { ok: false, error: "not_paid" });
  // The game sets this to the player's code when it opens the purchase screen.
  if (p.obfuscatedExternalAccountId && p.obfuscatedExternalAccountId !== code) return reply(403, { ok: false, error: "wrong_player" });

  const gems = PACKS[product] * Math.max(1, Math.min(10, Number(p.quantity) || 1));
  const rr = await rest("rpc/record_purchase", {
    method: "POST",
    body: JSON.stringify({
      p_token: token, p_code: code, p_secret: secret, p_product: product, p_gems: gems,
      p_order: typeof p.orderId === "string" ? p.orderId : null, p_test: p.purchaseType === 0,
    }),
  });
  if (!rr.ok) return reply(500, { ok: false, error: "db_error" });
  const r = await rr.json();
  if (!r.ok) return reply(403, { ok: false, error: r.error });
  return reply(200, { ok: true, gems, first: r.first, consumed: p.consumptionState === 1 });
});
