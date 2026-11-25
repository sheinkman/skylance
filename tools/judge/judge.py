#!/usr/bin/env python3
"""Skylance graphics judge.

Usage:
  python3 tools/judge/judge.py              # render, measure, AI review, write the report
  python3 tools/judge/judge.py --no-ai      # measurements only (fast, free)
  python3 tools/judge/judge.py --model models/gemini-3.1-pro-preview   # stricter, slower reviewer
  python3 tools/judge/judge.py --samples 3  # ask the AI 3 times per picture and average (default 2; scores vary ~1 point per run)

1. tools/judge/render.js draws every rider on every mount with the game's own code, measures each pair,
   and screenshots a normal level and the boss level of every realm.
2. Measured rules (exact): how much of the mount stays visible under the rider, whether the rider's hips sit on the
   mount's body, whether the legs reach the body (not floating), and the mount/rider size ratio.
3. AI review (Gemini vision) scores every picture against a written rubric and lists problems in plain words.
4. Writes tools/judge/out/report.html and summary.json. Exits with code 1 if anything fails.

The Gemini key is never read here: in the Claude cloud environment the network proxy adds it to requests for
generativelanguage.googleapis.com. Elsewhere, set GEMINI_API_KEY.
"""
import base64, html, json, os, re, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, 'out')
API = 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'
MODEL = 'models/gemini-3.8-flash'

# ---- measured rules: (name, test, severity, message) ----
def measured_flags(p):
    f = []
    if p.get('missing'): return [('fail', 'Sprite missing')]
    if not p['seatOnBody']: f.append(('fail', "The rider's hips are not over the mount's body (sitting on air or on legs/wings)."))
    if not p['legsReachBody']: f.append(('fail', 'The rider floats above the mount: the legs do not reach its body.'))
    if p['mountVisible'] < 0.45: f.append(('fail', f"Mount mostly hidden: only {p['mountVisible']:.0%} of it is visible under the rider (need 45%+, ideally 55%+)."))
    elif p['mountVisible'] < 0.55: f.append(('warn', f"Mount partly hidden: {p['mountVisible']:.0%} visible (ideally 55%+)."))
    if p['mountToRider'] < 0.45: f.append(('fail', f"Mount far too small for the rider: its body is {p['mountToRider']:.2f}x the rider's size (need 0.6x+)."))
    elif p['mountToRider'] < 0.6: f.append(('warn', f"Mount small for the rider: body {p['mountToRider']:.2f}x the rider's size (ideally 0.6x+)."))
    if p['mountToRider'] > 2.6: f.append(('warn', f"Mount very large next to the rider ({p['mountToRider']:.2f}x)."))
    if not 0.35 <= p['seatFrac'] <= 0.85: f.append(('warn', f"Seat is far from the mount's middle (at {p['seatFrac']:.0%} of its length)."))
    return f

RIDER_RUBRIC = """You are the art director of a cartoon arcade game where small knights ride giant insects and birds while jousting.
Judge this single sprite (one rider on one mount, seen from the side, facing right). Be strict: this is what players see.
Score each from 1 (terrible) to 10 (perfect):
- riding: does the rider clearly SIT ASTRIDE the mount, hips on its back and the near leg down its side, like a jockey? In a true side view only ONE leg is visible; if BOTH legs are visible on the viewer's side (side-saddle look), riding is at most 5 and say so. Standing on it, floating above it, or sitting on its head/tail/wings also scores low.
- mount_visible: can you clearly recognise the mount and see most of its body, or does the rider hide it?
- proportion: do the rider and mount sizes look right together (a mount big enough to carry the rider, not a tiny bug under a big knight)?
- placement: is the rider placed on a sensible part of the body (back/thorax), not hanging off the front or back?
Then list concrete problems a game artist could fix (empty list if none). verdict is "pass" if every score is 7 or more, otherwise "fix".
Reply with JSON only: {"riding":n,"mount_visible":n,"proportion":n,"placement":n,"problems":["..."],"verdict":"pass|fix"}"""

SCENE_RUBRIC = """You are the art director of a cartoon arcade game (Joust-like: knights riding flying insects over floating islands above water).
Judge this gameplay screenshot from a phone in landscape. Be strict but fair; ignore that it is a still frame.
Score each from 1 (terrible) to 10 (perfect):
- readability: can a child instantly tell the player, the enemies, the platforms and hazards apart from the background?
- consistency: do characters, platforms, background and UI look like one art style and a consistent scale?
- composition: is anything awkwardly overlapping, cut off at the screen edges, floating wrongly, or cluttered?
- polish: does it look like a finished commercial mobile game?
Then list concrete visual problems (empty list if none). verdict is "pass" if every score is 7 or more, otherwise "fix".
Reply with JSON only: {"readability":n,"consistency":n,"composition":n,"polish":n,"problems":["..."],"verdict":"pass|fix"}"""

def ask_avg(model, prompt, png_path, samples):
    # The AI's scores vary by about a point between runs, so each picture is reviewed several times and averaged.
    runs = [r for r in (ask(model, prompt, png_path) for _ in range(samples)) if not r.get('error')]
    if not runs: return {'error': 'no answer'}
    out = {'problems': [], 'runs': len(runs)}
    for k in runs[0]:
        vals = [r[k] for r in runs if isinstance(r.get(k), (int, float))]
        if vals: out[k] = round(sum(vals) / len(vals), 1)
    for r in runs: out['problems'] += [p for p in r.get('problems', []) if p not in out['problems']]
    nums = [v for k, v in out.items() if k not in ('runs',) and isinstance(v, (int, float))]
    out['verdict'] = 'pass' if nums and min(nums) >= 7 else 'fix'
    return out

def ask(model, prompt, png_path, tries=4):
    img = base64.b64encode(open(png_path, 'rb').read()).decode()
    body = {'model': model, 'messages': [{'role': 'user', 'content': [{'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' + img}}]}]}
    headers = {'Content-Type': 'application/json', 'Authorization': 'Bearer ' + os.environ.get('GEMINI_API_KEY', 'proxy-injected')}
    for i in range(tries):
        try:
            req = urllib.request.Request(API, data=json.dumps(body).encode(), headers=headers)
            txt = json.load(urllib.request.urlopen(req, timeout=180))['choices'][0]['message']['content']
            m = re.search(r'\{.*\}', txt, re.S)
            return json.loads(m.group(0))
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')
            if 'spending cap' in detail or 'spend cap' in detail:
                print('Gemini refused: the Google AI project has reached its monthly spending cap. Raise it at https://ai.studio/spend, '
                      'or run with --no-ai for measurements only.'); os._exit(2)
            err = f'HTTP {e.code}'; time.sleep(8 * (i + 1))
        except Exception as e:
            err = str(e)
            time.sleep(8 * (i + 1))
    return {'error': err}

def main():
    no_ai = '--no-ai' in sys.argv
    model = sys.argv[sys.argv.index('--model') + 1] if '--model' in sys.argv else MODEL
    samples = int(sys.argv[sys.argv.index('--samples') + 1]) if '--samples' in sys.argv else 2
    if '--skip-render' not in sys.argv:
        subprocess.run(['node', os.path.join(ROOT, 'render.js')], check=True)
    data = json.load(open(os.path.join(OUT, 'render.json')))
    pairs, scenes = data['pairs'], data['scenes']
    for p in pairs: p['flags'] = measured_flags(p)

    samples_used = None
    if not no_ai:
        samples_used = samples
        # The AI looks at one rider per mount and armor colour group (riders differ only in colour within a group),
        # plus every scene. Several requests run at once.
        seen, todo = set(), []
        for p in pairs:
            key = (p.get('mount'), p.get('kind'), p.get('rider', '')[:6])
            if p.get('file') and (p['mount'], p['rider']) not in seen:
                seen.add((p['mount'], p['rider']))
                if p['kind'] == 'enemy' or p['rider'] in ('rider_silver', 'rider_obsidian'): todo.append(p)
        jobs = [(p, RIDER_RUBRIC) for p in todo] + [(s, SCENE_RUBRIC) for s in scenes]
        print(f'AI review: {len(jobs)} pictures x {samples} opinions with {model}')
        with ThreadPoolExecutor(4) as ex:
            for item, res in zip([j[0] for j in jobs], ex.map(lambda j: ask_avg(model, j[1], os.path.join(OUT, j[0]['file']), samples), jobs)):
                item['ai'] = res
        for p in pairs:
            ai = p.get('ai')
            if ai and not ai.get('error') and ai.get('verdict') == 'fix':
                low = [k for k in ('riding', 'mount_visible', 'proportion', 'placement') if isinstance(ai.get(k), (int, float)) and ai[k] < 7]
                p['flags'].append(('warn', 'AI reviewer: low ' + ', '.join(low) if low else 'AI reviewer asks for a fix'))
        for s in scenes:
            ai = s.get('ai') or {}
            s['flags'] = [] if ai.get('error') or ai.get('verdict') != 'fix' else [('warn', 'AI reviewer asks for a fix')]

    def status(x):
        sev = [f[0] for f in x.get('flags', [])]
        return 'fail' if 'fail' in sev else 'warn' if 'warn' in sev else 'pass'
    for x in pairs + scenes: x['status'] = status(x)
    counts = {k: sum(1 for x in pairs + scenes if x['status'] == k) for k in ('pass', 'warn', 'fail')}
    json.dump({'model': None if no_ai else model, 'counts': counts, 'pairs': pairs, 'scenes': scenes}, open(os.path.join(OUT, 'summary.json'), 'w'), indent=1)
    write_report(pairs, scenes, counts, None if no_ai else model)
    print(f"pass {counts['pass']}  warn {counts['warn']}  fail {counts['fail']}  ->  tools/judge/out/report.html")
    for x in pairs + scenes:
        if x['status'] == 'fail': print('  FAIL', x['label'], '|', '; '.join(f[1] for f in x['flags'] if f[0] == 'fail'))
    sys.exit(1 if counts['fail'] else 0)

def write_report(pairs, scenes, counts, model):
    esc = html.escape
    def img64(f): return 'data:image/png;base64,' + base64.b64encode(open(os.path.join(OUT, f), 'rb').read()).decode()
    def scores(ai, keys):
        if not ai: return ''
        if ai.get('error'): return '<p class="muted">AI review failed</p>'
        cells = ''.join(f'<span class="sc {"lo" if isinstance(ai.get(k), (int, float)) and ai[k] < 7 else ""}">{esc(k.replace("_", " "))} <b>{esc(str(ai.get(k, "?")))}</b></span>' for k in keys)
        probs = ''.join(f'<li>{esc(str(p))}</li>' for p in ai.get('problems', [])[:5])
        return f'<div class="scores">{cells}</div>' + (f'<ul class="ai">{probs}</ul>' if probs else '')
    def card(x, keys, metrics=''):
        flags = ''.join(f'<li class="{s}">{esc(m)}</li>' for s, m in x.get('flags', []))
        return f'''<article class="card {x["status"]}"><div class="pic"><img src="{img64(x["file"])}" alt="{esc(x["label"])}"></div>
<div class="body"><h3><span class="dot"></span>{esc(x["label"])}</h3>{metrics}{f'<ul class="flags">{flags}</ul>' if flags else ''}{scores(x.get("ai"), keys)}</div></article>'''
    order = {'fail': 0, 'warn': 1, 'pass': 2}
    pc = ''.join(card(p, ('riding', 'mount_visible', 'proportion', 'placement'),
        f'<p class="m">Mount visible <b>{p["mountVisible"]:.0%}</b> · size ratio <b>{p["mountToRider"]:.2f}</b> · seat on body <b>{"yes" if p["seatOnBody"] else "no"}</b> · legs on mount <b>{"yes" if p["legsReachBody"] else "no"}</b></p>')
        for p in sorted([p for p in pairs if p.get('file')], key=lambda p: (order[p['status']], p['label'])))
    sc = ''.join(card(s, ('readability', 'consistency', 'composition', 'polish')) for s in sorted(scenes, key=lambda s: order[s['status']]))
    doc = f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Skylance Graphics Judge</title><style>
:root{{color-scheme:light dark;--bg:light-dark(#f4f5fb,#0d1024);--card:light-dark(#fff,#171b38);--ink:light-dark(#151a33,#eef0ff);--mut:light-dark(#5b6280,#a5abcf);--line:light-dark(#dfe2f0,#2a2f5a);--ok:#1f9d6b;--warn:#c98a00;--bad:#d33b3b}}
:root[data-theme=light]{{color-scheme:light}}:root[data-theme=dark]{{color-scheme:dark}}
*{{box-sizing:border-box;min-width:0}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif;padding:24px max(4vw,16px)}}
h1{{margin:0;font-size:30px}}h2{{margin:28px 0 10px;font-size:20px}}.muted{{color:var(--mut)}}
.tot{{display:flex;gap:10px;flex-wrap:wrap;margin:12px 0}}.tot span{{padding:6px 12px;border-radius:999px;background:var(--card);border:1px solid var(--line);font-weight:700}}
.tot .pass{{color:var(--ok)}}.tot .warn{{color:var(--warn)}}.tot .fail{{color:var(--bad)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr));gap:12px}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;overflow:hidden;display:flex;flex-direction:column}}
.card.fail{{border-color:var(--bad)}}.card.warn{{border-color:color-mix(in srgb,var(--warn) 60%,var(--line))}}
.pic{{background:#1b2350}}.pic img{{width:100%;display:block}}.body{{padding:10px 12px}}
h3{{margin:0 0 6px;font-size:15px;display:flex;gap:8px;align-items:center}}.dot{{width:10px;height:10px;border-radius:50%;flex:none;background:var(--ok)}}
.warn .dot{{background:var(--warn)}}.fail .dot{{background:var(--bad)}}.m{{margin:0 0 6px;font-size:13px;color:var(--mut)}}
ul{{margin:4px 0;padding-left:18px;font-size:13px}}.flags .fail{{color:var(--bad)}}.flags .warn{{color:var(--warn)}}.ai{{color:var(--mut)}}
.scores{{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}}.sc{{font-size:12px;padding:2px 8px;border-radius:6px;border:1px solid var(--line)}}.sc.lo{{border-color:var(--bad);color:var(--bad)}}
</style></head><body>
<h1>Skylance graphics judge</h1>
<p class="muted">Every rider drawn on every mount with the game's own code and measured, plus a normal and a boss level from every realm.
{"AI review by " + esc(model) + "." if model else "Measurements only (AI review skipped)."} Generated {time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())}.</p>
<div class="tot"><span class="fail">{counts["fail"]} fail</span><span class="warn">{counts["warn"]} warn</span><span class="pass">{counts["pass"]} pass</span></div>
<h2>Riders on mounts</h2><div class="grid">{pc}</div>
<h2>Gameplay screens</h2><div class="grid">{sc}</div>
</body></html>'''
    open(os.path.join(OUT, 'report.html'), 'w').write(doc)

if __name__ == '__main__':
    main()
