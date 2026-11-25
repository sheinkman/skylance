const { chromium } = require('playwright'); const fs = require('fs');
const path = require('path'); const SP = path.join(__dirname, 'out'), which = process.argv[2] || 'observe', realms = (process.argv[3] || '0-9').split('-').map(Number);
fs.mkdirSync(SP, { recursive: true });
(async () => {
  const br = await chromium.launch(); const pg = await br.newPage({ viewport: { width: 640, height: 360 } });
  const errs = []; pg.on('pageerror', e => errs.push(e.message));
  await pg.goto('file://' + path.resolve(__dirname, '../../www/index.html')); await pg.waitForTimeout(1500);
  await pg.addScriptTag({ content: fs.readFileSync(path.join(__dirname, 'qa_page.js'), 'utf8') });
  await pg.evaluate(() => { cancelAnimationFrame = () => {}; window.requestAnimationFrame = () => 0; }); // stop the real-time loop; we step manually
  const results = [];
  const only = process.argv[4] ? process.argv[4].split(',') : null;
  for (let r = realms[0]; r <= realms[1]; r++) for (let l = 1; l <= 10; l++) {
    if (only && !only.includes(`${r + 1}-${l}`)) continue;
    if (which === 'observe') {
      for (const how of (process.env.HOWS || 'high,low').split(',')) {
        const o = await pg.evaluate(([r, l, how]) => __qa.observe(r, l, false, how, 2400), [r, l, how]);
        results.push({ lvl: `${r + 1}-${l}`, how, ...o });
      }
    } else {
      for (const hard of [false, true]) {
        const c = await pg.evaluate(([r, l, hard]) => __qa.complete(r, l, hard, 40000), [r, l, hard]);
        results.push({ lvl: `${r + 1}-${l}${hard ? ' NM' : ''}`, ...c });
      }
    }
  }
  fs.writeFileSync(`${SP}/qa_${which}_${realms.join('-')}.json`, JSON.stringify({ results, errs }, null, 1));
  console.log('done', which, realms, 'page errors', errs.length);
  await br.close();
})();
