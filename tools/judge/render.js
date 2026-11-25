// Graphics judge, step 1: draws every rider/mount pair with the game's own drawing code and measures it,
// then takes a gameplay screenshot of every realm (a normal level and the boss level).
// Output: tools/judge/out/img/*.png and tools/judge/out/render.json
const { chromium } = require('playwright');
const http = require('http'), fs = require('fs'), path = require('path');

const ROOT = path.resolve(__dirname, '../../www'), OUT = path.join(__dirname, 'out'), IMG = path.join(OUT, 'img');
fs.mkdirSync(IMG, { recursive: true });
const TYPES = { '.html': 'text/html', '.png': 'image/png', '.jpg': 'image/jpeg', '.js': 'text/javascript' };
// Served over http (not file://) so the canvas can be read back for measuring.
const server = http.createServer((q, r) => {
  const u = decodeURIComponent(q.url.split(/[?#]/)[0]), f = path.join(ROOT, u === '/' ? 'index.html' : u);
  if (!f.startsWith(ROOT) || !fs.existsSync(f)) { r.writeHead(404); return r.end(); }
  r.writeHead(200, { 'Content-Type': TYPES[path.extname(f)] || 'application/octet-stream' }); r.end(fs.readFileSync(f));
});

(async () => {
  await new Promise(ok => server.listen(0, ok));
  const base = `http://localhost:${server.address().port}/`;
  const br = await chromium.launch();
  const ctx = await br.newContext({ viewport: { width: 844, height: 390 } });
  await ctx.route(/workers\.dev|supabase\.co/, r => r.abort()); // no backend needed
  const pg = await ctx.newPage(); const errors = []; pg.on('pageerror', e => errors.push(e.message));
  await pg.goto(base); await pg.waitForTimeout(2000);

  const pairs = await pg.evaluate(() => {
    const SCALE = 5, CW = 360, CH = 250, OX = 180, OY = 70;
    const toCanvas = (x, y) => [OX + SCALE * 1.25 * x, OY + SCALE * (24 + 1.25 * (y - 24))];
    const mk = () => { const c = document.createElement('canvas'); c.width = CW; c.height = CH; const g = c.getContext('2d'); g.translate(OX, OY); g.scale(SCALE, SCALE); g.translate(0, 24); g.scale(1.25, 1.25); g.translate(0, -24); return [c, g]; };
    const alpha = c => { const d = c.getContext('2d').getImageData(0, 0, CW, CH).data, a = new Uint8Array(CW * CH); for (let i = 0; i < a.length; i++) a[i] = d[i * 4 + 3] > 60 ? 1 : 0; return a; };
    const box = a => { let l = CW, r = -1, t = CH, b = -1, n = 0; for (let y = 0; y < CH; y++) for (let x = 0; x < CW; x++) if (a[y * CW + x]) { n++; if (x < l) l = x; if (x > r) r = x; if (y < t) t = y; if (y > b) b = y; } return { l, r, t, b, n }; };
    const out = [];
    const judgePair = (label, isP, mountKey, riderId, pal) => {
      const mid = (isP ? 'mount_' : 'insect_') + mountKey, spec = isP ? MOUNT_SPR[mountKey] : INSECT_SPR[mountKey];
      if (!IMG[mid] || !IMG[riderId] || !spec) { out.push({ label, missing: true }); return; }
      const still = { onGround: true, anim: 0, face: 1, wingT: 8, isPlayer: isP, pw: {} };
      const bodySpec = { ...spec, wing: { ...spec.wing, fly: 1 } }; // landed: wings folded away, so this is the body alone
      const [cm, gm] = mk(); const seat = drawMountSprite(gm, mid, bodySpec, pal, still);
      const [cr, gr] = mk(); drawRiderSprite(gr, riderId, seat, false, false);
      const M = alpha(cm), R = alpha(cr); let ov = 0; for (let i = 0; i < M.length; i++) if (M[i] && R[i]) ov++;
      const mb = box(M), rb = box(R), [sx, sy] = toCanvas(seat.x, seat.y);
      let onBody = false; for (let dy = -7; dy <= 7 && !onBody; dy++) for (let dx = -7; dx <= 7; dx++) { const x = Math.round(sx + dx), y = Math.round(sy + dy); if (x >= 0 && y >= 0 && x < CW && y < CH && M[y * CW + x]) { onBody = true; break; } }
      // The picture shown to the AI judge: wings in flight, then the rider, on the game's dark sky colour.
      const [cc, gc] = mk(); gc.save(); gc.setTransform(1, 0, 0, 1, 0, 0); gc.fillStyle = '#1b2350'; gc.fillRect(0, 0, CW, CH); gc.restore();
      const fly = { onGround: false, anim: 0, face: 1, wingT: 8, isPlayer: isP, pw: {} };
      const seat2 = drawMountSprite(gc, mid, spec, pal, fly); drawRiderSprite(gc, riderId, seat2, false, false);
      out.push({
        label, kind: isP ? 'player' : 'enemy', mount: mountKey, rider: riderId,
        mountVisible: +(1 - ov / Math.max(1, mb.n)).toFixed(3), mountToRider: +(mb.n / Math.max(1, rb.n)).toFixed(2),
        seatOnBody: onBody, seatFrac: +((sx - mb.l) / Math.max(1, mb.r - mb.l)).toFixed(2),
        legsReachBody: rb.b > mb.t + 2 && ov > 0, mountW: mb.r - mb.l, riderW: rb.r - rb.l, mountH: mb.b - mb.t, riderH: rb.b - rb.t,
        png: cc.toDataURL('image/png'),
      });
    };
    const armors = ['silver', 'gold', 'rose', 'obsidian'];
    Object.keys(MOUNTS).forEach((m, i) => armors.forEach(a => judgePair(`${a} knight on ${m}`, true, m, 'rider_' + a, { ...MOUNTS[m].pal, ...ARMORS[a].pal })));
    const tiers = ['scout', 'raider', 'elite'];
    Object.keys(INSECT_SPR).forEach(sp => tiers.forEach((t, i) => judgePair(`${t} on ${sp}`, false, sp, 'enemy_' + t, PAL_E[i])));
    return out;
  });
  for (const p of pairs) if (p.png) { const f = `pair_${p.label.replace(/\W+/g, '_')}.png`; fs.writeFileSync(path.join(IMG, f), Buffer.from(p.png.split(',')[1], 'base64')); p.file = 'img/' + f; delete p.png; }

  // Gameplay screenshots: level 4 and the boss level of every realm, a few seconds in.
  const scenes = [];
  await pg.evaluate(() => { localStorage.setItem('skylance.save.v1', JSON.stringify({ ageGroup: 'adult' })); });
  const realms = await pg.evaluate(() => REALMS.map(r => r.name));
  for (let r = 0; r < realms.length; r++) for (const l of [4, 10]) {
    await pg.evaluate(([r, l]) => __sky.startLevel(r, l), [r, l]); await pg.waitForTimeout(l === 10 ? 4200 : 3000);
    await pg.evaluate(() => { const P = __sky.P; if (P) { P.state = 'active'; P.invuln = 999; } });
    await pg.waitForTimeout(200);
    const f = `scene_${r + 1}_${l}.png`; await pg.screenshot({ path: path.join(IMG, f) });
    scenes.push({ label: `${realms[r]} level ${r + 1}-${l}${l === 10 ? ' (boss)' : ''}`, file: 'img/' + f });
  }
  fs.writeFileSync(path.join(OUT, 'render.json'), JSON.stringify({ pairs, scenes, errors }, null, 1));
  console.log(`rendered ${pairs.length} rider/mount pairs and ${scenes.length} scenes, page errors: ${errors.length}`);
  await br.close(); server.close();
})();
