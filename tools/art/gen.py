#!/usr/bin/env python3
"""Skylance art pipeline: generate sprites with Gemini, key out the background, trim and save.

Usage:
  python3 tools/art/gen.py [asset ids...] [--force]

Reads tools/art/assets.json. Each asset has a prompt, an output size, and whether
the background should be removed. Raw generations are cached in tools/art/raw/ so
re-keying or resizing never costs another API call (use --force to regenerate).

The API key is never read here: in the Claude cloud environment the network proxy
adds it to requests for generativelanguage.googleapis.com. Elsewhere, set
GEMINI_API_KEY and it is sent as a Bearer token.
"""
import base64, json, os, sys, time, urllib.request, io
from PIL import Image, ImageFilter

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, '..', '..', 'www', 'assets')
RAW = os.path.join(ROOT, 'raw')
API = 'https://generativelanguage.googleapis.com/v1beta/openai/images/generations'
MODEL = 'gemini-2.5-flash-image'

def generate(prompt, aspect):
    body = json.dumps({'model': MODEL, 'prompt': prompt + f' Aspect ratio {aspect}.', 'n': 1, 'response_format': 'b64_json'}).encode()
    key = os.environ.get('GEMINI_API_KEY', 'proxy-injected')
    req = urllib.request.Request(API, data=body, headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key})
    for attempt in range(6):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            raw = base64.b64decode(d['data'][0].get('b64_json') or '')
            Image.open(io.BytesIO(raw)).verify()
            return raw
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors='replace')
            if 'spending cap' in detail or 'spend cap' in detail:
                raise SystemExit('Gemini refused: the Google AI project has reached its monthly spending cap. '
                                 'Raise it at https://ai.studio/spend, then run this again.')
            print(f'  attempt {attempt + 1} failed: HTTP {e.code} {detail[:160]}')
            time.sleep(15 * (attempt + 1))
        except Exception as e:
            print(f'  attempt {attempt + 1} failed: {e}')
            time.sleep(15 * (attempt + 1))
    raise SystemExit('generation failed: ' + prompt[:60])

def key_out(img, key=None, holes=False):
    """Remove the background: flood-fill background-coloured pixels connected to the border,
    soften only the outline, and despill. Pixels inside the subject never turn transparent."""
    import numpy as np
    from PIL import ImageDraw
    img = img.convert('RGB')
    arr = np.asarray(img).astype(np.int32)
    h, w, _ = arr.shape
    border = np.concatenate([arr[0], arr[-1], arr[:, 0], arr[:, -1]])
    q = border // 24
    keys, counts = np.unique(q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2], return_counts=True)
    dom = keys[counts.argmax()]
    sel = border[(q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]) == dom]
    kc = np.median(sel, axis=0)
    d = np.sqrt(((arr - kc) ** 2).sum(axis=2))
    cand = Image.fromarray(((d < 75) * 255).astype(np.uint8), 'L').copy()
    for x in range(0, w, 4):
        for y in (0, h - 1):
            if cand.getpixel((x, y)) == 255: ImageDraw.floodfill(cand, (x, y), 128)
    for y in range(0, h, 4):
        for x in (0, w - 1):
            if cand.getpixel((x, y)) == 255: ImageDraw.floodfill(cand, (x, y), 128)
    bg = np.asarray(cand) == 128
    if holes: bg |= d < 55  # also clear enclosed pockets (e.g. inside letters)
    near = np.asarray(Image.fromarray((bg * 255).astype(np.uint8), 'L').filter(ImageFilter.MaxFilter(5))) > 0
    alpha = np.full((h, w), 255.0)
    alpha[bg] = 0
    edge = near & ~bg
    alpha[edge] = np.clip((d[edge] - 40) / 110 * 255, 0, 255)
    out = arr.copy()
    # despill on outline pixels: pull channels that the key colour boosts back toward the others
    m = edge
    kr, kg, kb = kc
    if kg >= kr and kg >= kb:
        out[..., 1][m] = np.minimum(out[..., 1][m], np.maximum(out[..., 0][m], out[..., 2][m]))
    else:
        if kr > kg: out[..., 0][m] = np.minimum(out[..., 0][m], np.maximum(out[..., 1][m], (out[..., 0][m] + out[..., 2][m]) // 2))
        if kb > kg: out[..., 2][m] = np.minimum(out[..., 2][m], np.maximum(out[..., 1][m], (out[..., 0][m] + out[..., 2][m]) // 2))
    rgba = np.dstack([out, alpha]).astype(np.uint8)
    return Image.fromarray(rgba, 'RGBA')

def process(a, raw):
    img = Image.open(io.BytesIO(raw))
    if a.get('key', True):
        bgname = a.get('bg', 'magenta')
        target = (0, 255, 0) if 'green' in bgname else (0, 0, 0) if 'black' in bgname else (255, 0, 255)
        img = key_out(img, holes=a.get('holes', False))
        bbox = img.getchannel('A').point(lambda v: 255 if v > 24 else 0).getbbox()
        if bbox: img = img.crop(bbox)
    else:
        img = img.convert('RGB')
    if a.get('crop'):  # [left, top, right, bottom] fractions, for backgrounds
        l, t, r_, b_ = a['crop']; W, H = img.size
        img = img.crop((int(l * W), int(t * H), int(r_ * W), int(b_ * H)))
    tw, th = a.get('size', [None, None])
    W, H = img.size
    if tw and th and not a.get('key', True): img = img.resize((tw, th), Image.LANCZOS)
    elif th: img = img.resize((max(1, round(W * th / H)), th), Image.LANCZOS)
    elif tw: img = img.resize((tw, max(1, round(H * tw / W))), Image.LANCZOS)
    return img

def main():
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    force = '--force' in sys.argv
    spec = json.load(open(os.path.join(ROOT, 'assets.json')))
    style = spec['style']
    os.makedirs(RAW, exist_ok=True); os.makedirs(OUT, exist_ok=True)
    for a in spec['assets']:
        if args and a['id'] not in args: continue
        rawp = os.path.join(RAW, a['id'] + '.png')
        if force or not os.path.exists(rawp):
            bg = ' Isolated on a solid flat pure ' + a.get('bg', 'magenta (#FF00FF)') + ' background, nothing else in the background, no shadow, no ground, no text, no border.' if a.get('key', True) else ''
            st = spec.get('styles', {}).get(a.get('style', ''), '')
            prompt = a['prompt'] + ' ' + (st or style) + bg
            print('generating', a['id'])
            open(rawp, 'wb').write(generate(prompt, a.get('aspect', '1:1')))
        img = process(a, open(rawp, 'rb').read())
        ext = '.png' if a.get('key', True) else '.jpg'
        path = os.path.join(OUT, a['id'] + ext)
        if ext == '.jpg': img.save(path, quality=86, optimize=True)
        else: img.save(path, optimize=True)
        print('  saved', os.path.relpath(path), img.size)

if __name__ == '__main__':
    main()
