---
name: skylance-art
description: Create or change Skylance game art (riders, mounts, enemy insects, bosses, islands, backgrounds, props) with the Gemini pipeline, wire it into the game, and prove it with the graphics judge. Use for any request to add, redraw, resize or fix sprites or visuals in Skylance.
---

# Making Skylance art

Every picture in the game comes from `tools/art/assets.json` through `tools/art/gen.py` (Gemini image generation,
background removal, trimming, resizing) into `www/assets/`. Nothing ships until `tools/judge/judge.py` passes.

## 0. Before you start

- Gemini is used for both generating and judging. If anything returns `RESOURCE_EXHAUSTED` or mentions a
  **spending cap**, stop and tell the user to raise the monthly cap at https://ai.studio/spend. Don't retry in a loop.
- In the Claude cloud environment the network proxy adds the Gemini key; never put a key in code or chat.
  Elsewhere set `GEMINI_API_KEY`.
- Back up any sprite you are about to replace (copy it to the scratchpad) so you can compare and roll back.

## 1. Pick the style and write the prompt

Add or edit an entry in `tools/art/assets.json`:
`{"id", "style", "prompt", "size": [w|null, h|null], "aspect"?, "bg"?, "holes"?, "key"?}`

| Style | Used for | Built-in description (added automatically) |
|---|---|---|
| `toon` | Riders (player knights, enemy warriors) | Chunky cute cartoon, big head, thin dark outline, side profile facing right |
| `bug` | Mounts and enemy insects | Semi-realistic painterly insect, side profile facing right, body horizontal |
| `boss` | Bosses | Painterly fantasy creature, dramatic lighting, side view facing right |
| `scene` | Realm backgrounds (`bg_*`, 16:9, 1280x720, `"key": false`) | Painterly background, no characters, no platforms, no text |
| `prop` | Islands, shores, gems, cocoons, logo | Painterly asset, clean silhouette, side view |

Prompt rules learned the hard way (each one fixed a real bug):

- **Riders:** describe the exact riding pose, or Gemini draws a standing figure even when asked to sit:
  "sitting astride an invisible horse like a jockey: hips resting on an invisible saddle, knee bent, lower leg
  hanging straight down. ONLY ONE LEG IS VISIBLE: the near leg ... the far leg is completely hidden".
  Always end with "Full body, no mount, no animal, no saddle, nothing under the rider." Lance held level, pointing right.
- **Mounts and insects:** "NO wings at all" (the game draws animated wings itself), "body perfectly horizontal",
  "big enough to be ridden: plump, sturdy body", "bright and well lit" (dark thin bodies vanish on night skies).
- **Everything:** facing right, side profile, one subject only, plain background.
- **Backgrounds:** leave the lower part calm (water goes there), keep the top fifth simple (the top bar sits there),
  no strong detail at the far left and right edges.

Background removal: the default key colour is magenta. Use `"bg": "bright green (#00FF00)"` when the subject is pink,
red or purple, and `"holes": true` when the subject has enclosed gaps (between legs and body, inside wings, lance
and arm) so leftover background pockets are removed too.

## 2. Generate

```bash
python3 tools/art/gen.py <asset ids...> --force
```
Raw images are cached in `tools/art/raw/`; re-running without `--force` only re-cuts and resizes (free).
Look at every result yourself (Read the PNG) before using it: pose, facing direction, one leg, no wings, no leftover
background colour. Regenerate with a sharper prompt if it's wrong; don't fix a bad pose with code.

## 3. Wire it into the game (`www/index.html`)

- New sprite ids go in `SPRITE_LIST`.
- **Mounts** (`MOUNT_SPR`) and **enemy insects** (`INSECT_SPR`): `w` = drawn length, optional `maxh` = height limit
  (needed for long-legged or square pictures), `seat` = where the rider's hips go (fraction of the length from the
  tail end), `back` = how far down from the top of the picture the back is, plus `wing` settings for the animated wings.
  Shared knobs: `MOUNT_SCALE`, `MOUNT_MAXH`, `RIDER_HIP` (hip point inside the rider picture), `SEAT_SINK`.
- **Islands:** `SURF` holds the fraction of the island picture above the walkable top edge.
- **Bosses:** `BOSS_SPR` holds `[drawn width, vertical anchor]`.
- Gameplay hit boxes are separate (`RW`, `RH`); art changes never change how the game plays.

To find a seat, measure where the body actually is in the picture (opaque rows at a few x positions with PIL),
then set `seat`/`back` on the body, not on legs, wings or empty space.

## 4. Judge it (the gate)

```bash
python3 tools/judge/judge.py --no-ai   # measurements, about 1 minute, free: iterate with this
python3 tools/judge/judge.py           # full run with the AI art director, about 5 minutes
```
Open `tools/judge/out/report.html`. Rules for riders: mount at least 45% visible (ideally 55%), hips on the body,
legs reaching the body, mount body 0.6-2.6x the rider's size, seat near the middle. The AI scores riding pose
(one visible leg), mount visibility, proportion and placement, and every realm's normal and boss screen for
readability, consistency, composition and polish. Each picture is reviewed twice and averaged; treat a 1-point change
as noise and look at the pictures yourself before reacting to it.

**Done means:** the judge reports 0 fail and the AI verdicts pass, you looked at the report yourself, and
`node tools/qa/qa.js complete 0-9` still finishes every level (art changes can move bosses or riders).

## 5. Ship

Rebuild the APK (`npx cap sync android`, then `./gradlew assembleDebug` in `android/`), publish the web version for
testers with `python3 tools/web/deploy.py` (https://play.skylance.workers.dev), commit (`tools/art/assets.json`, `www/assets/*`, `www/index.html`) and push.
