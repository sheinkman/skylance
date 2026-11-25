# Graphics judge

Checks how the game looks, so art problems are caught before players see them.

```bash
python3 tools/judge/judge.py            # full run: measurements + AI review (~5 min)
python3 tools/judge/judge.py --no-ai    # measurements only (~1 min, no API calls)
```
Open `tools/judge/out/report.html` for every picture with its scores and problems (failures first).
The command exits with code 1 if anything fails, so it can gate a release.

## What it checks

**Riders on mounts (measured exactly).** Every rider (4 armors, 3 enemy types) is drawn on every mount and insect with
the game's own drawing code, then measured pixel by pixel:

| Rule | Fail | Warn |
|---|---|---|
| Mount still visible under the rider | under 45% | under 55% |
| Rider's hips over the mount's body (not air, legs or wings) | not on body | |
| Rider's legs reach the body (not floating) | no | |
| Mount body size compared with the rider | under 0.45x | under 0.6x or over 2.6x |
| Seat near the middle of the mount | | outside 35-85% of its length |

**AI review (Gemini vision).** One rider of each colour group per mount, plus a normal level and the boss level of
every realm, are scored 1-10 against a written art-director rubric (riding pose, mount visible, proportion,
placement; for screens: readability, consistency, composition, polish), with a list of concrete problems.
Each picture is reviewed twice and averaged (`--samples N` to change), since AI scores vary by about a point between
runs. Use `--model models/gemini-3.1-pro-preview` for a stricter, slower review.

## Tuning riders and mounts

In `www/index.html`: `MOUNT_SPR` (player mounts) and `INSECT_SPR` (enemy insects) hold each mount's size (`w`, optional
`maxh`) and saddle point (`seat` = fraction of its length from the tail, `back` = fraction of its height from the top).
`MOUNT_SCALE`, `RIDER_HIP` and `SEAT_SINK` apply to all. Change one, run `--no-ai`, look at the report.

The Gemini key is never in this code: in the Claude cloud environment the network proxy adds it. Elsewhere set
`GEMINI_API_KEY`.
