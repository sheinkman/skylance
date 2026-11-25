# Gameplay QA bot

Plays the game at many times real speed in a headless browser and checks gameplay rules every frame.
Run from the repository root (needs Node.js and Playwright):

```bash
node tools/qa/qa.js observe 0-9
```
Watches all 100 levels twice (player hovering high, then low near the water) for 40 seconds each and reports:
enemies or cocoons lost in the sea, enemies stuck inside platforms for 10+ frames, enemies not moving for 5 seconds,
positions outside the play area or not finite, the invincible player dying, and any script error.

```bash
node tools/qa/qa.js complete 0-9
```
Plays every level in normal and Nightmare mode to the end (200 runs) and reports any that cannot be finished.

Results are written to `tools/qa/out/` as JSON. A realm range (`0-4`) and a level list (`2-10,5-10`) can be passed
to run part of the game. The game exposes a test hook, `window.__sky.step(n)`, that advances n frames instantly.

Expected results as of 25 Nov 2026: 0 sea losses of enemies, 0 embedded, 0 errors, 200/200 levels completed.
A few "stuck" reports in the low run are enemies circling the motionless test player, not real freezes.
