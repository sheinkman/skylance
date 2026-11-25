// Injected into the game page: invariant checks while fast-forwarding.
window.__qa = {
  observe(r, l, hard, how, frames) {
    const S = __sky, out = { sea: [], seaCocoon: 0, embed: [], stuck: [], oob: [], nan: [], invulnDeath: 0, errors: [], enemiesSeen: 0 };
    try { S.startLevel(r, l, hard); } catch (e) { out.errors.push('start: ' + e.message); return out; }
    const SEA = 332, W = 640, track = new WeakMap(), seen = new WeakSet();
    let prevEnemies = [], prevCocoons = [], lastInfo = new WeakMap(), x0 = 100;
    const embedOnce = new WeakSet(), stuckOnce = new WeakSet();
    for (let f = 0; f < frames; f++) {
      const P = S.P;
      if (P) { // drive the player: invincible, hovering high or low
        if (P.state === 'spawn') P.state = 'active';
        P.invuln = 999; x0 = (x0 + 0.7) % W;
        P.x = x0; P.y = how === 'high' ? 36 : how === 'mid' ? 200 : SEA - 72; P.vx = 0; P.vy = 0; P.onGround = false;
      }
      const pState = P && P.state;
      for (const e of S.enemies) lastInfo.set(e, { x: e.x, y: e.y, h: e.h, vy: e.vy, kind: e.kind, tier: e.tier, state: e.state, frost: !!(P && P.pw && P.pw.frost > 0), sticky: e.sticky > 0, flapCd: e.flapCd, ty: e.ai && e.ai.ty, ground: e.onGround, bump: e.bump, insect: e.insect || e.mount || '', f });
      const cInfo = new WeakMap(); for (const c of S.cocoons) cInfo.set(c, { y: c.y, h: c.h || 12 });
      try { S.step(1); } catch (e) { out.errors.push(`frame ${f}: ${e.message}`); break; }
      if (S.game.state !== 'play') break;
      if (P && pState === 'active' && S.P && S.P.state === 'dead') out.invulnDeath++;
      const now = new Set(S.enemies);
      for (const e of prevEnemies) if (!now.has(e) || e.dead) {
        const i = lastInfo.get(e); if (i && i.y + i.h >= SEA - 8 && !e.defeated) out.sea.push(i);
      }
      const nowC = new Set(S.cocoons);
      for (const c of prevCocoons) if (!nowC.has(c)) { const i = cInfo.get(c); if (i && i.y + i.h >= SEA - 8) out.seaCocoon++; }
      for (const e of S.enemies) {
        if (e.dead) continue;
        if (!seen.has(e)) { seen.add(e); out.enemiesSeen++; }
        if (![e.x, e.y, e.vx, e.vy].every(Number.isFinite)) { out.nan.push({ kind: e.kind, f }); continue; }
        if (e.state !== 'active') continue;
        if (e.y < -60 || e.y > SEA + 12 || e.x < -40 || e.x > W + 40) out.oob.push({ kind: e.kind, x: Math.round(e.x), y: Math.round(e.y), f });
        let inside = null;
        for (const p of S.plats) {
          if (p.gone || p.off) continue;
          for (const off of [0, -640, 640]) {
            const ex = e.x + off, ox = Math.min(ex + e.w, p.x + p.w) - Math.max(ex, p.x), oy = Math.min(e.y + e.h, p.y + p.h) - Math.max(e.y, p.y);
            if (ox > 4 && oy > 4) inside = p;
          }
        }
        e.__in = inside ? (e.__in || 0) + 1 : 0;
        if (e.__in === 10 && !embedOnce.has(e)) { const p = inside; embedOnce.add(e); out.embed.push({ kind: e.kind, tier: e.tier, x: Math.round(e.x), y: Math.round(e.y), vx: e.vx, vy: e.vy, ground: e.onGround, plat: [Math.round(p.x), Math.round(p.y), p.w, Math.round(p.h)], moving: !!p.move, f }); }
        const t = track.get(e);
        if (!t) track.set(e, { x: e.x, y: e.y, f });
        else if (f - t.f >= 300) {
          const moved = Math.abs(e.x - t.x) + Math.abs(e.y - t.y);
          if (moved < 2 && e.kind !== 'walker' && !(P && P.pw && P.pw.frost > 0) && !stuckOnce.has(e)) { stuckOnce.add(e); out.stuck.push({ kind: e.kind, tier: e.tier, x: Math.round(e.x), y: Math.round(e.y), ground: e.onGround, vx: +e.vx.toFixed(2), vy: +e.vy.toFixed(2), dir: e.ai && e.ai.dir, ty: e.ai && Math.round(e.ai.ty), bump: e.bump, hit: e.hit, py: S.P && Math.round(S.P.y), px: S.P && Math.round(S.P.x), stall: e.stall, under: S.plats.filter(p => Math.abs(p.y - (e.y + e.h)) < 4 && e.x + e.w > p.x && e.x < p.x + p.w).map(p => [Math.round(p.x), Math.round(p.y), p.w]), side: S.plats.filter(p => p.y < e.y + e.h - 2 && p.y + p.h > e.y && Math.min(Math.abs(p.x - (e.x + e.w)), Math.abs(e.x - (p.x + p.w))) < 3).map(p => [Math.round(p.x), Math.round(p.y), p.w]), f }); }
          track.set(e, { x: e.x, y: e.y, f });
        }
      }
      prevEnemies = S.enemies.slice(); prevCocoons = S.cocoons.slice();
    }
    return out;
  },
  // Plays the level to the end by placing the player above targets (proves it can be completed).
  complete(r, l, hard, maxFrames) {
    const S = __sky; S.startLevel(r, l, hard);
    for (let f = 0; f < maxFrames; f++) {
      const P = S.P;
      if (S.game.state !== 'play') return { state: S.game.state, f, title: document.getElementById('r-title').textContent };
      if (P) {
        if (P.state === 'spawn') P.state = 'active';
        if (P.state === 'active') {
          P.invuln = 99;
          const b = S.boss;
          if (b) {
            if ((b.type === 'wyrm' || b.type === 'toad') && (b.ph === 'under' || b.y > 300)) { P.x = b.x - 9; P.y = 150; P.vy = 0; }
            else if (!(b.type === 'eclipse' && b.fade < 0.5) && (f % 24 === 0 || P.y > b.y)) { P.x = b.x - 9; P.y = b.y - b.h / 2 - 30; P.vy = 1.5; }
          } else {
            const t = S.enemies.find(e => e.state !== 'spawn' && !e.dead) || S.cocoons[0];
            if (t && t.kind === 'walker') { P.x = (t.x - 60 + 640) % 640; P.y = t.y; P.vy = 0; P.face = 1; P.en = 999; P.fireCd = 0; S.fireWeapon(); }
            else if (t) { P.x = t.x; P.y = t.y - 10; P.vy = 0; P.onGround = false; }
          }
        }
      }
      S.step(1);
    }
    return { state: 'timeout', enemies: S.enemies.length, cocoons: S.cocoons.length, boss: S.boss && { type: S.boss.type, hp: S.boss.hp, ph: S.boss.ph } };
  },
};
