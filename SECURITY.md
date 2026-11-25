# Security notes

What protects Skylance players and the backend, and the rules to keep when changing the game.

## What the game accepts from outside

| Input | Where it comes from | Protection |
|---|---|---|
| Challenge links (`#c-R-L-SCORE-CODE`, `skylance://challenge/...`) | Anyone can craft one | Strict pattern match (digits and a 6-character code only, length-capped); shown with `textContent`, never as HTML |
| Saved progress (`localStorage`) | Can be edited or corrupted on the device | `loadSave()` copies only known fields, checks types, caps numbers and drops unknown items |
| Install referrer | Google Play | Only a `ref=` code matching `[a-z0-9]{6}` is used |
| Backend replies and settings | Skylance backend | Only `ok === true` counts; gem amounts, counts and settings are clamped to safe ranges |
| Purchase events | Play Billing | Product must be one of the 4 known packs; gems come from the server's reply, capped; each token is applied once |

## Browser and WebView protection

- A Content Security Policy in `www/index.html` allows scripts only from the game itself. Network requests can go only to the game's own files and the Skylance backend, so injected code could not load outside scripts or send data elsewhere.
- No `eval`, no external scripts and no `innerHTML` with outside data. The only third-party SDK is Google AdMob, in the Android app, and it runs outside the game's web page.
- Android: WebView debugging is on only in debug builds, mixed content and plain-HTTP traffic are off, and the file provider is not exported. Permissions: Internet and network state, plus the advertising ID permission that AdMob adds (for under-13 players, ad requests are child-directed, so the ID is not used for ads).

## Backend

```
Game  ->  Skylance backend (Cloudflare Worker, skylance-api.skylance.workers.dev)  ->  Supabase database
```

- The game talks only to the backend (`backend/worker.js`). It validates every request, hashes the caller's IP address for rate limiting, and calls the database with a secret key that exists only in Cloudflare's secret store.
- The database accepts only that key. It stores just the key's SHA-256 hash, in a `private` schema the public API does not expose. Its 4 callable functions (`api_register`, `api_claim`, `api_collect`, `api_ping`) do nothing without the key, and the older functions are no longer callable at all.
- Tables have row-level security on, no policies, and no table grants: nobody can read or change them through the API.
- Game settings (video reward, daily video limit, invite rewards) come from the backend's `/v1/config`, so they can change without an app update. The game clamps them to safe ranges.
- A scheduled trigger on the backend calls the database every 2 days so the free Supabase project never pauses.
- Rate limits:
  - at most 30 new players per network per hour
  - at most 5 accepted referrals per network per day
  - at most 10 referrals per inviter per day
  - a global brake of 3,000 new players per 10 minutes
- Networks are identified only by a salted SHA-256 hash of the IP address. Raw addresses are never stored, and the log is pruned after 2 days.
- `purchases` records each Google Play purchase token once. The `verify-purchase` edge function accepts calls only from the backend (it checks the backend key with the database). `record_purchase` can be called only by that function (service role), which first confirms the purchase with the Google Play Developer API. The Google service-account key lives only in Supabase's secret store.
- The game contains no keys at all. The backend key, the Supabase service-role key, the database password and the Cloudflare API token must never appear in this repository or the app.

## Rules to keep

1. Never put a secret key in `www/index.html` or the Android project. Anything shipped in the app can be read by anyone.
2. Never commit the release signing key (`*.jks`, `*.keystore`). Store it and its passwords in a safe place with a backup: losing it means you cannot update the game on Google Play. Enrolling in Play App Signing lets Google keep the app signing key.
3. Gems and progress live on the device, so players can edit them; that only affects their own game. Purchased gems are granted only after the `verify-purchase` server function has confirmed the purchase with Google, so tools that fake purchase responses get nothing. Keep it that way: never grant paid gems from the device's word alone.
4. When adding UI that shows outside data, use `textContent`, not `innerHTML`.
5. Before each release, run `npm audit` and the Supabase security advisor. The advisor lists the 4 `api_*` functions as publicly callable; that is expected, since they refuse every call without the backend key.
