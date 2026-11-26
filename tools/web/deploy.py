#!/usr/bin/env python3
"""Publish the web version of Skylance at https://play.skylance.workers.dev (and the privacy policy at /privacy).

Usage:
  python3 tools/web/deploy.py

How it works: every file in www/ (plus docs/privacy.html) is stored in a Cloudflare Workers KV namespace, and a tiny
Worker ("play") serves them with the right content types and edge caching. Old files no longer in www/ are removed.
Each deploy gets a new version number, so players get the new files right away.

Needs a Cloudflare API token with Workers Scripts and Workers KV Storage edit rights. In the Claude cloud environment
the network proxy adds it to requests for api.cloudflare.com; elsewhere set CLOUDFLARE_API_TOKEN.
"""
import base64, json, os, subprocess, sys, tempfile, time, urllib.request

ACCOUNT = 'bf26b3cba48c9511d9739647aa6e764b'
SCRIPT = 'play'
NAMESPACE = 'skylance-web'
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
API = f'https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}'
TOKEN = os.environ.get('CLOUDFLARE_API_TOKEN', 'proxy-injected')

WORKER = r"""
const TYPES = { html: 'text/html; charset=utf-8', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', webp: 'image/webp',
  js: 'text/javascript', css: 'text/css', json: 'application/json', svg: 'image/svg+xml', ico: 'image/x-icon' };
export default {
  async fetch(req, env, ctx) {
    if (req.method !== 'GET' && req.method !== 'HEAD') return new Response('Method not allowed', { status: 405 });
    const url = new URL(req.url);
    let key = decodeURIComponent(url.pathname).replace(/^\/+/, '');
    if (key === '') key = 'index.html';
    if (key === 'privacy' || key === 'privacy/') key = 'privacy.html';
    if (!/^[A-Za-z0-9._\/-]{1,200}$/.test(key) || key.includes('..')) return new Response('Not found', { status: 404 });
    const cache = caches.default, ck = new Request(`${url.origin}/${key}?v=${env.VERSION}`);
    let res = await cache.match(ck);
    if (res) return res;
    const body = await env.SITE.get(key, 'arrayBuffer');
    if (!body) return new Response('Not found', { status: 404, headers: { 'content-type': 'text/plain' } });
    const ext = key.split('.').pop().toLowerCase();
    res = new Response(body, { headers: {
      'content-type': TYPES[ext] || 'application/octet-stream',
      'cache-control': ext === 'html' ? 'public, max-age=60' : 'public, max-age=86400',
      'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer', 'x-frame-options': 'SAMEORIGIN',
    } });
    ctx.waitUntil(cache.put(ck, res.clone()));
    return res;
  },
};
"""

def call(method, path, body=None, raw=None, ctype='application/json'):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(API + path, data=data, method=method, headers={'Authorization': 'Bearer ' + TOKEN, 'Content-Type': ctype})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise SystemExit(f'{method} {path} failed: HTTP {e.code} {e.read().decode()[:400]}')

def site_files():
    files = {}
    www = os.path.join(ROOT, 'www')
    for d, _, names in os.walk(www):
        for n in names:
            if n.startswith('.'): continue
            p = os.path.join(d, n)
            files[os.path.relpath(p, www).replace(os.sep, '/')] = open(p, 'rb').read()
    priv = os.path.join(ROOT, 'docs', 'privacy.html')
    if os.path.exists(priv):  # the policy is written as page content; give it a full document shell here
        files['privacy.html'] = (b'<!doctype html><html lang="en"><head><meta charset="utf-8">'
                                 b'<meta name="viewport" content="width=device-width,initial-scale=1"></head><body>'
                                 + open(priv, 'rb').read() + b'</body></html>')
    return files

def main():
    # 1. storage
    spaces = call('GET', '/storage/kv/namespaces?per_page=100')['result']
    ns = next((s['id'] for s in spaces if s['title'] == NAMESPACE), None)
    if not ns:
        ns = call('POST', '/storage/kv/namespaces', {'title': NAMESPACE})['result']['id']
        print('created storage', NAMESPACE)
    # 2. files
    files = site_files()
    batch = [{'key': k, 'value': base64.b64encode(v).decode(), 'base64': True} for k, v in files.items()]
    call('PUT', f'/storage/kv/namespaces/{ns}/bulk', batch)
    print(f'uploaded {len(files)} files ({sum(len(v) for v in files.values()) / 1e6:.1f} MB)')
    keys = [k['name'] for k in call('GET', f'/storage/kv/namespaces/{ns}/keys?limit=1000')['result']]
    stale = [k for k in keys if k not in files]
    if stale:
        call('POST', f'/storage/kv/namespaces/{ns}/bulk/delete', stale)
        print('removed', len(stale), 'old files')
    # 3. the serving Worker (a new VERSION makes every cached file fresh)
    meta = {'main_module': 'worker.js', 'compatibility_date': '2025-09-01', 'bindings': [
        {'type': 'kv_namespace', 'name': 'SITE', 'namespace_id': ns},
        {'type': 'plain_text', 'name': 'VERSION', 'text': str(int(time.time()))}]}
    with tempfile.TemporaryDirectory() as t:
        open(os.path.join(t, 'worker.js'), 'w').write(WORKER)
        open(os.path.join(t, 'meta.json'), 'w').write(json.dumps(meta))
        out = subprocess.run(['curl', '-s', '-m', '120', '-X', 'PUT', f'{API}/workers/scripts/{SCRIPT}', '-H', 'Authorization: Bearer ' + TOKEN,
                              '-F', f'metadata=@{t}/meta.json;type=application/json', '-F', f'worker.js=@{t}/worker.js;type=application/javascript+module'],
                             capture_output=True, text=True).stdout
    r = json.loads(out)
    if not r.get('success'): raise SystemExit('worker upload failed: ' + json.dumps(r.get('errors')))
    call('POST', f'/workers/scripts/{SCRIPT}/subdomain', {'enabled': True, 'previews_enabled': False})
    sub = call('GET', '/workers/subdomain')['result']['subdomain']
    print(f'live: https://{SCRIPT}.{sub}.workers.dev  (privacy policy: /privacy)')

if __name__ == '__main__':
    main()
